#!/usr/bin/env python3

# Regex support: see tmgrammar.py, which parses the grammar's regexes.
#
# Rule support: see tmgrammar.py, which reads the grammar. Also unsupported
# (error) in Vim:
#   end captures of a group (only capture "0" of an end regex is supported)
#   captures inside lookarounds
#
# Not detected:
#   $1-style capture references in scope names aren't filled in; the part of
#     the scope before them decides the highlight group
#
# Behaviour differences: \w matches non-ASCII letters in both (it becomes Vim's
# \k, which also counts emoji and other symbols as word characters), but \w
# inside a class, \W, \d and \D only cover ASCII in Vim, while Oniguruma's
# also cover non-ASCII letters and digits. Oniguruma's \s matches any
# whitespace, including newlines and no-break spaces; Vim's \s only matches
# space and tab (inside a class, \s is expanded to include \r and \n).

import datetime
import re

import tmgrammar
from tmgrammar import SELF, ConvertError, LOOKAROUND, capture_path, children, zero_width

MAINTAINER = "Joshua Raphael"
URL = "https://github.com/joshraphael/rascript-syntax"
REMARK = "Syntax grammar for RAScript, a RetroAchievements.org DSL"

# Files bigger than SYNC_MAX_BYTES don't highlight from the top of the file
# (syntax sync fromstart), which takes about 2 microseconds per byte, ~0.4s at
# 200 KB; they start SYNC_MINLINES lines above the screen instead. SYNC_MINLINES
# only needs to be longer than any block comment or string: the longest in the
# RAScripts on GitHub are 291 and 56 lines
SYNC_MAX_BYTES = 200000
SYNC_MINLINES = 1000


# --------------------------------------------------------------------------
# Regex writing: turns a parsed tree into a Vim very magic regex. The
# converter writes every pattern as /\%#=1\v.../ (see ENGINE) because very
# magic is closest to Oniguruma: ( ) | + ? { work without backslashes.
#   e.g. tree of "0x[0-9a-fA-F]+" -> 0x[0-9a-fA-F]+
#        tree of "a{2,}?"         -> a{-2,}
#        tree of "(?<=\.)\w"      -> %(\.)@<=\w
# --------------------------------------------------------------------------

# Starts every pattern to pick Vim's backtracking regex engine (\%#=1) instead
# of its default NFA engine. Grammars use long word lists and lookarounds
# (e.g. the built-in function names), which the NFA engine is many times
# slower at; on a 1,000 line RAScript file highlighting went from about 3.8s
# to 0.3s, and long lines no longer lose highlighting
ENGINE = r"\%#=1"

# Maps a group kind -> the text that closes that group in Vim, e.g. "(?=" ->
# ")@=". In Oniguruma the type is marked at the start of the group; in Vim
# every group opens with %( and the type is marked after the closing ):
#   (x)     capture group       -> %(x)
#   (?:x)   non-capturing group -> %(x)
#   (?>x)   atomic group        -> %(x)@>
#   (?=x)   lookahead           -> %(x)@=
#   (?!x)   negative lookahead  -> %(x)@!
#   (?<=x)  lookbehind          -> %(x)@<=
#   (?<!x)  negative lookbehind -> %(x)@<!
# Capture groups become %( too: Vim never needs the captured text, the parser
# only numbers them so the grammar's "captures" can refer to them
GROUPS = {"(": ")", "(?:": ")", "(?>": ")@>", "(?=": ")@=", "(?!": ")@!", "(?<=": ")@<=", "(?<!": ")@<!"}

# Maps an Oniguruma escape letter -> the Vim escape for the same set of
# characters, e.g. "h" -> r"\x":
#   \w  word character   -> \k   (Vim's \w is ASCII only; \k is a keyword
#                                 character from syntax iskeyword, which
#                                 includes non-ASCII letters)
#   \s  whitespace       -> \s
#   \d  digit 0-9        -> \d
#   \h  hex digit        -> \x   (Vim's \h means something else: letter or _)
ESC = {"w": r"\k", "W": r"\W", "s": r"\s", "S": r"\S", "d": r"\d", "D": r"\D", "h": r"\x", "H": r"\X"}

# Maps a class escape letter -> the characters it stands for, written as
# ranges so they can go inside Vim's [...]; Vim doesn't understand \w \d \s
# inside brackets. e.g. [\w-] -> [0-9A-Za-z_\-]
#   \w  letters, digits, _      \d  digits
#   \s  whitespace (\d11 and \d12 are Vim's vertical tab and form feed)
#   \h  hex digits
CLASS_ESC = {"w": "0-9A-Za-z_", "d": "0-9", "s": r" \t\r\n\d11\d12", "h": "0-9A-Fa-f"}

# Maps an invisible character -> how Vim writes it in a pattern, the reverse
# of CONTROL, so the generated file never contains a raw tab or newline
VIM_CONTROL = {"\t": r"\t", "\n": r"\n", "\r": r"\r"}

# Word characters (what \w matches). Used two ways:
#  - render(): these are the only ASCII characters that can be written bare in
#    a Vim very magic (\v) pattern; every other one is special (= < > @ % {
#    ...), so it gets a backslash
#  - edge_is_word(): deciding whether \b is the start or end of a word
WORD = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def class_is_word(node):
    """Whether a [...] class can match a word character; a negated class counts as not."""
    _, negated, items = node
    return not negated and any(i[1] in "wdh" if i[0] == "esc" else any(c in WORD for c in i[1:]) for i in items)


def edge_is_word(node, at_end):
    r"""Whether the first (or, with at_end, last) character node matches is a word char.

      edge_is_word(<"if">, False)      -> True   "i" is a word char
      edge_is_word(<"\.">, False)      -> False
      edge_is_word(<"a|\.">, False)    -> True   either branch counts
      edge_is_word(<"(?=x)\.">, False) -> False  lookahead skipped, "." checked
    """
    kind = node[0]
    if kind == "char":
        return node[1] in WORD
    if kind == "esc":
        return node[1] in "wdh"
    if kind == "class":
        return class_is_word(node)
    if kind == "seq":
        items = [x for x in node[1] if not zero_width(x)]
        return bool(items) and edge_is_word(items[-1 if at_end else 0], at_end)
    if kind == "group" and node[1] in LOOKAROUND:
        return False
    return any(edge_is_word(c, at_end) for c in children(node))


def word_boundaries(node):
    r"""Picks a Vim word boundary for every \b in a tree.

    Vim has no \b, only < (a word starts here) and > (a word ends here). Each
    \b becomes ("wordb", vim), choosing by what is next to it in its sequence:
      \bif\b    -> <if>        word after the first, word before the last
      x\b\.     -> x>\.       word before, punctuation after: a word ends
      (a|\b)    -> %(<|>)      nothing next to it, so allow either
    Inner sequences are done first, so their boundaries already count as zero
    width when an outer \b looks inside them.
    """
    kind = node[0]
    if kind in ("seq", "alt"):
        items = [word_boundaries(x) for x in node[1]]
        if kind == "seq":
            for i, item in enumerate(items):
                if item == ("wordb",):
                    starts = i + 1 < len(items) and edge_is_word(items[i + 1], False)
                    ends = i > 0 and edge_is_word(items[i - 1], True)
                    items[i] = ("wordb", "<" if starts and not ends else ">" if ends and not starts else "%(<|>)")
        return (kind, items)
    if kind == "group":
        return node[:2] + (word_boundaries(node[2]),) + node[3:]
    if kind == "rep":
        return (kind, word_boundaries(node[1])) + node[2:]
    return node


def render_class(node):
    r"""Writes a [...] class node in Vim syntax.

    \w \d \s \h expand through CLASS_ESC; ] ^ - \ get a backslash, because those
    are the only characters special inside Vim's brackets:
      [\w-]      -> [0-9A-Za-z_\-]
      [^\s"]     -> [^ \t\r\n\d11\d12"]
      [\.\]a-z^] -> [.\]a-z\^]
    """
    _, negated, items = node
    parts = []
    for item in items:
        if item[0] == "esc":
            parts.append(CLASS_ESC[item[1]])
        else:
            # ("range", "a", "z") -> "a-z", real tab -> "\t", "]" -> "\]"
            parts.append("-".join(VIM_CONTROL.get(c, "\\" + c if c in "]^-\\" else c) for c in item[1:]))
    return "[" + "^" * negated + "".join(parts) + "]"


def quantifier(lo, hi, lazy):
    """Writes a repeat count in Vim syntax.

    Greedy * + ? stay as they are; everything else uses braces, where a
    leading - makes Vim match as few as possible (lazy):
      (0, None, False) -> *         (2, 4, False) -> {2,4}
      (0, None, True)  -> {-}       (2, 4, True)  -> {-2,4}
      (3, 3, False)    -> {3}       (2, None, False) -> {2,}
    """
    if not lazy and (lo, hi) in ((0, None), (1, None), (0, 1)):
        return {(0, None): "*", (1, None): "+", (0, 1): "?"}[(lo, hi)]
    body = "" if lazy and (lo, hi) == (0, None) else str(lo) if lo == hi else f"{lo},{'' if hi is None else hi}"
    return "{" + "-" * lazy + body + "}"


class Vim(tmgrammar.Dialect):
    """Writes tree nodes as very magic text."""

    def group(self, kind, inner):
        # every group opens with %( (non-capturing); GROUPS gives the closer
        return "%(" + inner + GROUPS[kind]

    def quantifier(self, lo, hi, lazy):
        return quantifier(lo, hi, lazy)

    def char(self, c):
        if c in WORD or c == " " or ord(c) > 127:
            return c
        # tab/newline -> \t \n, other ASCII punctuation -> backslash + char
        return VIM_CONTROL.get(c, "\\" + c)

    def esc(self, c):
        return ESC[c]

    def char_class(self, node):
        return render_class(node)

    def anchor(self, c):
        # Vim's ^ and $ are only anchors at the start and end of a pattern;
        # \_^ and \_$ work anywhere in it, like Oniguruma's
        return "\\_" + c

    def any(self):
        return "."

    def wordb(self, node):
        # word_boundaries picked its Vim text
        return node[1]


VIM = Vim()


def render(node):
    """Writes a tree node (and everything under it) as very magic text."""
    return tmgrammar.render(node, VIM)


def render_capture(root, target):
    r"""Writes a pattern that matches only capture group `target` of a regex.

    The rest of the regex becomes context that must be present but is not
    part of the match: what comes before the group is a lookbehind %(...)@<=,
    what comes after it a lookahead %(...)@=. e.g. for (\bclass\b)[\t ]*(\w+):
      target 1 -> <class>%([\t ]*%(\w+))@=
      target 2 -> %(%(<class>)[\t ]*)@<=\w+

    Why not just mark the group with Vim's \zs and \ze? A capture item is
    contained in the rule's match, and Vim searches for contained items
    starting from where the previous one ended, so text before the group
    would already be behind the search position. Lookbehind only checks it.

    Alternations on the way to the group: only the branch holding the group
    can produce it, so the capture pattern uses just that branch. But in
    a|(b) TextMate tries a first, so (b) only counts where a would not have
    matched; a negative lookahead guard %(a)@! in front keeps that rule:
      (?:(if)|(\w+))\(  target 2 -> %(%(if)\()@!\w+%(\()@=
    The guard includes what follows the alternation ("rest"), because a only
    wins if the whole regex can still match after it.

    Repeats on the way to the group: when a group repeats, TextMate scopes
    only its last iteration. So the repeat is split into the earlier
    iterations (one fewer, going into the lookbehind) plus one final
    iteration holding the group:
      (?:(\d)\.)+x  target 1 -> %(%(%(\d)\.)*)@<=\d%(\.x)@=
    """
    path = capture_path(root, target)

    def split(node, rest):
        """Returns (before, group, after) for the part of the regex in node.

        rest is the rendered text that follows node in the whole regex, used
        by alternation guards. before is a list of (text, zero_width) items,
        so trailing anchors and lookarounds can be kept out of the lookbehind
        (see below).
        """
        kind = node[0]
        if kind == "group" and node[3] == target:
            group = render(node[2])
            # a|b must stay grouped once other text is put around it
            return [], "%(" + group + ")" if node[2][0] == "alt" else group, ""
        if kind == "seq":
            # split around the one item that leads to the target
            items = node[1]
            i = next(i for i, x in enumerate(items) if id(x) in path)
            after = "".join(map(render, items[i + 1:]))
            before, group, a = split(items[i], after + rest)
            return [(render(x), zero_width(x)) for x in items[:i]] + before, group, a + after
        if kind == "alt":
            # keep only the branch with the target, guarded by the ones before it
            k = next(i for i, b in enumerate(node[1]) if id(b) in path)
            guards = [("%(" + render(b) + rest + ")@!", True) for b in node[1][:k]]
            before, group, after = split(node[1][k], rest)
            return guards + before, group, after
        if kind == "group":
            # a group wrapping the target; step inside it
            if node[1] in LOOKAROUND:
                raise ConvertError("captures inside lookarounds are not supported")
            return split(node[2], rest)
        # a repeat: earlier iterations (one fewer, at least zero), then the
        # last one with the target; x{2,4} -> x{1,3} before, x? -> none before
        _, child, lo, hi, lazy = node
        lo, hi = max(lo, 1) - 1, None if hi is None else hi - 1
        before, group, after = split(child, rest)
        return ([] if hi == 0 else [(render(child) + quantifier(lo, hi, lazy), False)]) + before, group, after

    before, group, after = split(root, "")
    # zero-width items at the end of the context (e.g. < in \b(\w+)) can stay
    # in front of the group instead of going in the lookbehind
    last = max((i for i, (_, zw) in enumerate(before) if not zw), default=-1)
    behind = "".join(text for text, _ in before[:last + 1])
    out = "".join(text for text, _ in before[last + 1:]) + group
    if behind:
        out = "%(" + behind + ")@<=" + out
    if after:
        out += "%(" + after + ")@="
    return out


# --------------------------------------------------------------------------
# Colors: maps a TextMate scope name -> a standard Vim highlight group. The
# generated file links each rule's group to one of these, so it is colored by
# whatever colorscheme the user has, like Vim's built-in syntax files.
# --------------------------------------------------------------------------

# Scope prefix -> Vim highlight group (see :help group-name). The longest
# prefix that matches wins, e.g. for "constant.numeric.hexadecimal.rascript":
#   constant.numeric.hexadecimal  (not listed)
#   constant.numeric              -> Number   <- used
#   constant                      -> Constant (shorter, so ignored)
SCOPE_MAP = {
    "comment": "Comment", "punctuation.definition.comment": "Comment",
    "string": "String", "punctuation.definition.string": "String",
    "constant": "Constant", "constant.numeric": "Number", "constant.character": "Character",
    "constant.character.escape": "SpecialChar", "constant.language.boolean": "Boolean",
    "keyword": "Keyword", "keyword.control": "Statement", "keyword.operator": "Operator",
    "keyword.other": "PreProc", "storage": "StorageClass", "storage.type": "Type",
    "entity.name": "Identifier", "entity.name.function": "Function", "entity.name.class": "Type",
    "entity.name.type": "Type", "entity.name.tag": "Tag", "entity.other.attribute-name": "Identifier",
    "support": "Special", "support.function": "Function", "support.class": "Type",
    "support.type": "Type", "support.constant": "Constant",
    "variable": "Identifier", "variable.language": "Special",
    "punctuation": "Delimiter", "punctuation.definition.template-expression": "Special",
    "punctuation.section.embedded": "Special", "invalid": "Error",
    "markup.heading": "Title", "markup.underline": "Underlined", "meta.preprocessor": "PreProc",
}


def scope_to_vim(scope):
    """Returns the Vim group for a scope, or None if no prefix is in SCOPE_MAP.
      "constant.numeric.decimal.rascript" -> "Number"
      "meta.something.rascript"           -> None
    """
    return tmgrammar.scope_lookup(SCOPE_MAP, scope)


def camel(key):
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", key) if w)


class Converter:
    def __init__(self, grammar):
        self.grammar = grammar
        self.lang = grammar.raw.get("scopeName", "source.tmlang").split(".")[-1]
        # the top-level patterns are written as the cluster @<lang>Top
        self.top_name = self.lang + "Top"
        self.group_names = {}
        self.highlight_links = []  # (rule group, Vim group) pairs for highlight lines
        self.used_clusters = set()  # repository keys (or SELF) that something includes

    def assign(self, node, base):
        """Names each rule after its repository key and position."""
        if node.kind == "include":
            return
        nested = node.is_rule
        if nested:
            name, n = base, 2
            while name in self.group_names.values():
                name, n = f"{base}{n}", n + 1
            self.group_names[id(node)], base = name, name
        inline = [p for p in node.patterns if p.kind != "include"]
        for i, p in enumerate(inline):
            single = len(inline) == 1 and not nested
            self.assign(p, base if single else f"{base}_{i + 1}")

    def walk(self, patterns, visit):
        """grammar.walk, noting every repository entry it includes."""
        seen = set()
        self.grammar.walk(patterns, visit, seen)
        self.used_clusters |= seen

    def contains(self, patterns):
        """A pattern list -> the names Vim needs in contains=.

        Rules are listed by group name; includes become clusters (@name), so
        a repository entry is written once and shared by everything including it.
          [{"include": "#numbers"}, {"match": ...}] -> ["@rascriptNumbers", "rascriptStrings_1"]
        """
        out = []
        for p in patterns:
            if p.kind == "include":
                key = p.target
                out.append("@" + (self.top_name if key == SELF else self.lang + camel(key)))
            elif p.is_rule:
                out.append(self.group_names[id(p)])
            else:
                out.extend(self.contains(p.patterns))
        return out

    def link(self, group, scope):
        """Records that a rule's group should be colored like its scope."""
        vim = scope_to_vim(scope)
        if vim:
            self.highlight_links.append((group, vim))

    @staticmethod
    def pattern(node, icase, target=None):
        r"""Wraps a tree as a Vim pattern: /\%#=1\v.../ (see ENGINE), with \c
        if case-insensitive.

        With target, the pattern matches only that capture group (see
        render_capture).
        """
        body = render(node) if target is None else render_capture(node, target)
        return "/" + ENGINE + "\\v" + "\\c" * icase + body + "/"

    def captures(self, regex, name, prefix, out):
        r"""Writes a rule's capture items and works out the scope for the
        whole match of one of its regexes (a tmgrammar.Regex).

        Returns (scope, capture group names, Vim pattern). The whole match is
        colored by the rule's name, unless a capture covers all of it, in
        which case the capture's name wins:
          capture "0"                       always the whole match
          a group around the entire regex   e.g. capture "1" of ([a-zA-Z_]\w*)
        Every other named capture becomes its own contained syntax match,
        named prefix + number (e.g. rascriptHeader_1_c2) and added to out; the
        rule's match then lists them in contains=.
        """
        node, icase, caps = word_boundaries(regex.tree), regex.icase, regex.captures
        whole_groups, whole = regex.whole_groups, regex.whole_scope(name)
        groups = []
        for key, cap in sorted(caps.items(), key=lambda kv: int(kv[0])):
            if key == "0" or not cap.get("name") or int(key) in whole_groups:
                continue
            try:
                pat = self.pattern(node, icase, int(key))
            except ConvertError as e:
                raise ConvertError(f"{regex.label}: capture {key}: {e}") from None
            groups.append(f"{prefix}{key}")
            out.append(f"syntax match {groups[-1]} {pat} contained")
            self.link(groups[-1], cap["name"])
        return whole, groups, self.pattern(node, icase)

    def emit_match(self, rule, g, contained, caps_out):
        """A match rule -> one syntax match line (capture items go in caps_out)."""
        whole, groups, pat = self.captures(rule.match, rule.name, f"{g}_c", caps_out)
        self.link(g, whole)
        return [f"syntax match {g} {pat}" + (f" contains={','.join(groups)}" if groups else "") + contained]

    def emit_region(self, rule, g, contained, caps_out):
        r"""A begin/end rule -> a syntax region line (two lines with begin captures).

        e.g. strings: syntax region rascriptStrings matchgroup=rascriptStrings_begin
             start=/\%#=1\v\"/ matchgroup=rascriptStrings_end end=/\%#=1\v\"/
        matchgroup= puts the begin and end text in their own groups ({g}_begin,
        {g}_end) so they can be colored separately from the body, and so the
        region's contents are never matched inside them. contains= lists the
        rules allowed inside the region (the rule's own "patterns").

        A matchgroup start can't contain other items, so begin captures that
        cover part of the begin text need a different shape: a syntax match
        for the begin text (which can contain the capture items) whose
        nextgroup= is the body region, starting right where the match ended:
          syntax region {g}_body start=/\%#=1\v%(\_.)@=/ matchgroup={g}_end end=... contained
          syntax match {g} <begin> contains={g}_bc1,... nextgroup={g}_body
        %(\_.)@= is zero-width and matches anywhere, so the body starts
        immediately; contained keeps it from starting anywhere else.
        """
        name = rule.name
        bwhole, bgroups, begin = self.captures(rule.begin, name, f"{g}_bc", caps_out)
        lines, body = [], g
        if bgroups:
            body = g + "_body"
            lines.append(f"syntax match {g} {begin} contains={','.join(bgroups)} nextgroup={body}{contained}")
            self.link(g, bwhole)
            start, contained = "start=/" + ENGINE + r"\v%(\_.)@=/", " contained"
        else:
            self.link(g + "_begin", bwhole)
            start = f"matchgroup={g}_begin start={begin}"
        ewhole, egroups, end = self.captures(rule.end, name, f"{g}_ec", [])
        if egroups:
            raise ConvertError(f"{rule.label}: end captures other than 0 are not supported")
        self.link(g + "_end", ewhole)
        members = self.contains(rule.patterns)
        # contentName colors only the body; name colors begin, body and end
        self.link(body, rule.content_name or name)
        # the region goes first so the begin match, defined after it, wins
        lines.insert(0, f"syntax region {body} {start} matchgroup={g}_end end={end}"
                        + (f" contains={','.join(members)}" if members else "") + contained)
        return lines

    def convert(self):
        for key, entry in self.grammar.repository.items():
            self.assign(entry, self.lang + camel(key))
        self.assign(self.grammar.patterns, self.top_name)
        top_patterns = self.grammar.patterns.patterns

        # rules reachable from the top level; every other rule only appears
        # inside a region, so it is marked contained (Vim won't try it elsewhere)
        top = set()
        self.walk(top_patterns, lambda r: top.add(id(r)))

        # every rule, in the order TextMate would try them: each rule followed
        # by the rules inside it (if it is a region), each listed once
        order = []

        def visit(rule):
            if all(r is not rule for r in order):
                order.append(rule)
                self.walk(rule.patterns if rule.kind == "region" else [], visit)

        self.walk(top_patterns, visit)
        # When several rules could match at the same spot, TextMate uses the
        # first one in the grammar but Vim uses the last one defined. Writing
        # the rules in reverse makes Vim pick the same rule VS Code does, e.g.
        # "if" is a control keyword, not the catch-all variable rule
        rules_out, caps_out = [], []
        for rule in reversed(order):
            g = self.group_names[id(rule)]
            emit = self.emit_match if rule.kind == "match" else self.emit_region
            contained = "" if id(rule) in top else " contained"
            rules_out += [f'" {rule.label}'] + emit(rule, g, contained, caps_out)

        # one cluster per included repository entry, listing the rules in it
        # e.g. syntax cluster rascriptNumbers contains=rascriptNumbers_1,rascriptNumbers_2
        clusters_out = []
        for key, entry in self.grammar.repository.items():
            if key in self.used_clusters:
                members = [self.group_names[id(entry)]] if entry.is_rule else self.contains(entry.patterns)
                clusters_out.append(f"syntax cluster {self.lang}{camel(key)} contains={','.join(members) or 'NONE'}")
        if SELF in self.used_clusters:
            clusters_out.append(f"syntax cluster {self.top_name} contains={','.join(self.contains(top_patterns))}")

        version = self.grammar.raw.get("version")
        out = ['" Vim syntax file',
               f'" Language:    {self.grammar.raw.get("name", self.lang)}',
               f'" Maintainer:  {MAINTAINER}',
               f'" URL:         {URL}',
               f'" Last Change: {datetime.datetime.now(datetime.timezone.utc):%Y %b %d}']
        out += [f'" Version:     {version}'] if version else []
        out += [f'" Remark:      {REMARK}', "",
                "if exists('b:current_syntax')", "  finish", "endif", "",
                '" Save the user\'s cpoptions and use Vim defaults while this file loads;',
                '" some flags (e.g. C) change how Vim script is parsed',
                "let s:cpo_save = &cpo", "set cpo&vim", "",
                "syntax case match",
                '" Word characters for the < and > word boundaries in patterns (Vim\'s',
                '" version of the grammar\'s \\b); fixed here so the user\'s iskeyword',
                '" setting can\'t change highlighting, e.g. matching "if" inside "my_if"',
                "syntax iskeyword @,48-57,_,192-255", "",
                '" Highlight from the top of the file so multi-line comments and strings',
                f'" are always right, except in files over {SYNC_MAX_BYTES // 1000} KB, where that is slow;',
                f'" those start {SYNC_MINLINES} lines above the screen instead',
                f"if line2byte(line('$') + 1) > {SYNC_MAX_BYTES}",
                f"  syntax sync minlines={SYNC_MINLINES}",
                "else",
                "  syntax sync fromstart",
                "endif", ""]
        out += ['" Repository entries'] + clusters_out + [""] if clusters_out else []
        out += ['" Rules: later definitions take priority'] + rules_out + [""]
        out += ['" Captures'] + caps_out + [""] if caps_out else []
        # one line per colored rule, e.g. "highlight default link rascriptControls Statement";
        # "default" lets a user's own highlight settings override these
        width = max((len(g) for g, _ in self.highlight_links), default=0)
        out += [f"highlight default link {g.ljust(width)} {vim}" for g, vim in self.highlight_links]
        out += [""] if self.highlight_links else []
        out += [f"let b:current_syntax = '{self.lang}'", "",
                '" Restore the user\'s cpoptions',
                "let &cpo = s:cpo_save", "unlet s:cpo_save"]
        return "\n".join(out) + "\n"


def main():
    tmgrammar.main("Convert a TextMate grammar into a Vim syntax file, written to stdout.",
                   lambda grammar: Converter(grammar).convert())


if __name__ == "__main__":
    main()
