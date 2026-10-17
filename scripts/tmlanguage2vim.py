#!/usr/bin/env python3

import datetime
import json
import re
import sys

MAINTAINER = "Joshua Raphael"
URL = "https://github.com/joshraphael/rascript-syntax"
REMARK = "Syntax grammar for RAScript, a RetroAchievements.org DSL"


class ConvertError(Exception):
    pass


# --------------------------------------------------------------------------
# Regex parsing: turns an Oniguruma regex string into a tree of tuples.
# Each node is a tuple whose first item names its type; the rest are its
# fields, read by position (node[1], node[2], ...):
#   ("seq", items)                  items: nodes matched one after another
#   ("alt", branches)               branches: nodes, any one may match (a|b)
#   ("group", closer, child, index) ( ) group; closer: Vim closing text from
#                                   GROUPS; index: capture number or None
#   ("rep", child, lo, hi, lazy)    child repeated lo..hi times (hi None =
#                                   no limit); from * + ? {n,m}
#   ("char", c)                     one literal character
#   ("esc", c)                      class escape letter from ESC, e.g. "d"
#   ("class", vim, wordy)           a [...] class, already in Vim syntax;
#                                   wordy: it can match a word character
#   ("anchor", vim)                 ^ or $, stored as its Vim text
#   ("any", ".")                    . (any character)
#   ("wordb",)                      \b (word boundary); only exists while
#                                   parsing, then becomes an anchor < or >
# e.g. "a+|b" -> ("alt", [("seq", [("rep", ("char", "a"), 1, None, False)]),
#                         ("seq", [("char", "b")])])
# --------------------------------------------------------------------------

# Splits a regex into tokens, e.g. "0x[0-9a-f]+" -> "0", "x", "[0-9a-f]", "+".
# Alternatives, tried left to right:
#   \\.                        backslash escape: \d \b \( ...
#   \[\^?\]?(?:\\.|[^\]\\])*\] a whole [...] class; a ] right after [ or [^ is literal
#   \(\?(?:...)                group opener: (?: (?> (?= (?! (?<= (?<! or (?i); any
#                              other (?... is still one token so parse() can reject it
#   (?:[*+?]|\{...\})\??       quantifier: * + ? {n} {n,} {n,m}, with ? making it lazy
#   .                          any other single character, including ( ) |
TOKEN = re.compile(r"\\.|\[\^?\]?(?:\\.|[^\]\\])*\]|\(\?(?:<?[=!]|[:>]|i\)|[^:)]*[:)]?)|(?:[*+?]|\{\d+(?:,\d*)?\})\??|.", re.S)

# Splits a quantifier token into (symbol, n, comma, m, lazy):
#   "+"     -> ("+", None, None, None, "")    short form * + ?
#   "{2,4}" -> (None, "2", ",", "4", "")      {n} exactly n, {n,} n or more, {n,m}
#   "*?"    -> ("*", None, None, None, "?")   trailing ? = lazy
# n = min repeats, m = max repeats; lazy = match as few repeats as possible
QUANTIFIER_PARTS = re.compile(r"(?:([*+?])|\{(\d+)(,?)(\d*)\})(\??)")

# Maps an Oniguruma group opener -> the text that closes that group in Vim,
# e.g. "(?=" -> ")@=". Only these group types are supported. In Oniguruma the
# type is marked at the start of the group; in Vim every group opens with %(
# and the type is marked after the closing ):
#   (x)     capture group       -> %(x)
#   (?:x)   non-capturing group -> %(x)
#   (?>x)   atomic group        -> %(x)@>
#   (?=x)   lookahead           -> %(x)@=     x must follow
#   (?!x)   negative lookahead  -> %(x)@!     x must not follow
#   (?<=x)  lookbehind          -> %(x)@<=    x must come before
#   (?<!x)  negative lookbehind -> %(x)@<!    x must not come before
# Capture groups become %( too: Vim never needs the captured text, the parser
# only numbers them so the grammar's "captures" can refer to them
GROUPS = {"(": ")", "(?:": ")", "(?>": ")@>", "(?=": ")@=", "(?!": ")@!", "(?<=": ")@<=", "(?<!": ")@<!"}

# Maps an Oniguruma escape letter -> the Vim escape for the same set of
# characters, e.g. "h" -> r"\x". Uppercase is the opposite set (\W = any
# non-word character). Escaped letters not listed here or in CONTROL are an
# error (see escape_char).
#   \w  word character: letter, digit or _    -> \w
#   \s  whitespace: space, tab, newline ...   -> \s
#   \d  digit 0-9                             -> \d
#   \h  hex digit 0-9 a-f A-F                 -> \x   (Vim's \h means something
#                                                      else: letter or _)
ESC = {"w": r"\w", "W": r"\W", "s": r"\s", "S": r"\S", "d": r"\d", "D": r"\D", "h": r"\x", "H": r"\X"}

# Maps an escape letter for an invisible character -> that actual character,
# e.g. "t" -> a real tab. The parser stores \t \n \r as plain ("char", c)
# nodes, the same as a typed letter:
#   \t  tab
#   \n  newline
#   \r  carriage return
CONTROL = {"t": "\t", "n": "\n", "r": "\r"}

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

# Vim closers of the lookaround groups (see GROUPS). Lookarounds check text
# without consuming it, so they don't count as a neighbouring character
LOOKAROUND = (")@=", ")@!", ")@<=", ")@<!")


def parse(src):
    """Returns (tree, ignore_case, number of capture groups)."""
    toks = TOKEN.findall(src)
    icase = toks[:1] == ["(?i)"]
    toks = toks[icase:][::-1]
    count = [0]

    def alt():
        branches = [seq()]
        while toks and toks[-1] == "|":
            toks.pop()
            branches.append(seq())
        return branches[0] if len(branches) == 1 else ("alt", branches)

    def seq():
        items = []
        while toks and toks[-1] not in ("|", ")"):
            t = toks.pop()
            q = QUANTIFIER_PARTS.fullmatch(t)
            if q:
                if not items or items[-1][0] in ("rep", "anchor"):
                    raise ConvertError(f"nothing to repeat before {t!r}")
                sym, lo, comma, hi, lazy = q.groups()
                lo, hi = {"*": (0, None), "+": (1, None), "?": (0, 1)}[sym] if sym else (
                    int(lo), int(hi) if hi else None if comma else int(lo))
                items[-1] = ("rep", items[-1], lo, hi, bool(lazy))
            elif t in GROUPS:
                index = None
                if t == "(":
                    count[0] += 1
                    index = count[0]
                child = alt()
                if not toks or toks.pop() != ")":
                    raise ConvertError("missing ')'")
                items.append(("group", GROUPS[t], child, index))
            elif t.startswith("[") and len(t) > 1:
                items.append(char_class(t))
            elif t in ("^", "$"):
                items.append(("anchor", "\\_" + t))
            elif t == ".":
                items.append(("any", "."))
            elif t == r"\b":
                items.append(("wordb",))
            elif t[0] == "\\" and t[1:] in ESC:
                items.append(("esc", t[1]))
            elif t[0] == "\\":
                items.append(("char", escape_char(t[1])))
            elif t.startswith("(?"):
                raise ConvertError(f"unsupported group {t!r}")
            else:
                items.append(("char", t))
        # Vim has no \b, only < (a word starts here) and > (a word ends here).
        # Pick one by looking at what is next to the \b in this sequence:
        #   \bif\b    -> <if>        word after the first, word before the last
        #   x\b\.     -> x>\.       word before, punctuation after: a word ends
        #   (a|\b)    -> %(a|%(<|>)) nothing next to it, so allow either
        for i, item in enumerate(items):
            if item[0] == "wordb":
                starts = i + 1 < len(items) and edge_is_word(items[i + 1], False)
                ends = i > 0 and edge_is_word(items[i - 1], True)
                items[i] = ("anchor", "<" if starts and not ends else ">" if ends and not starts else "%(<|>)")
        return ("seq", items)

    node = alt()
    if toks:
        raise ConvertError("unbalanced ')'")
    return node, icase, count[0]


def escape_char(c):
    if c in CONTROL:
        return CONTROL[c]
    if c.isalnum():
        raise ConvertError(f"unsupported escape \\{c}")
    return c


def char_class(token):
    r"""Translates a [...] class token into a ("class", vim, wordy) node.

    Reads the inside one item at a time, where an item is a character or an
    escape, optionally followed by -character for a range (a-z). \w \d \s \h
    expand through CLASS_ESC; other items are kept, with ] ^ - \ escaped
    because those are the only characters special inside Vim's brackets.
    wordy is True if the class can match a word character (used for \b);
    a negated class counts as not wordy.

    Examples (token -> returned node):
      r"[a-zA-Z_]"   -> ("class", r"[a-zA-Z_]", True)              nothing to change
      r"[\w-]"       -> ("class", r"[0-9A-Za-z_\-]", True)         \w expanded, - escaped
      r'[^\s"]'      -> ("class", r'[^ \t\r\n\d11\d12"]', False)   \s expanded, ^ kept
      r"[\.\]a-z^]"  -> ("class", r"[.\]a-z\^]", True)             \. unescaped, ] ^ escaped
      r"[[:alpha:]]" -> raises ConvertError
    """
    # "[^\s"a-z]" -> negated = True
    negated = token.startswith("[^")
    if "[:" in token:
        raise ConvertError("POSIX character classes are not supported")
    parts, wordy = [], False
    # split the inside into (lo, hi) items, hi set only for ranges like a-z;
    # lo/hi are one char or a backslash escape, and a - with nothing after it
    # is a literal dash. e.g. inside of [^\s"a-z] is \s"a-z -> (\s, ""), (", ""), (a, z)
    for lo, hi in re.findall(r"(\\.|[^\\])(?:-(\\.|[^\\]))?", token[1 + negated:-1]):
        # "\s" -> " \t\r\n\d11\d12"
        if lo[0] == "\\" and lo[1] in CLASS_ESC and not hi:
            parts.append(CLASS_ESC[lo[1]])
            wordy |= lo[1] in "wdh"
            continue
        # one character, or two for a range: '"' -> ['"'], "a"-"z" -> ["a", "z"],
        # "\." -> ["."], "\t" -> [real tab]
        chars = [escape_char(x[1]) if x[0] == "\\" else x for x in (lo, hi) if x]
        wordy |= any(c in WORD for c in chars)
        # back to Vim text: ["a", "z"] -> "a-z", [real tab] -> "\t", ["]"] -> "\]"
        parts.append("-".join(VIM_CONTROL.get(c, "\\" + c if c in "]^-\\" else c) for c in chars))
    # -> "[^ \t\r\n\d11\d12"a-z]"
    return ("class", "[" + "^" * negated + "".join(parts) + "]", wordy and not negated)


def children(node):
    """The nodes directly inside a node (none for single characters)."""
    if node[0] in ("seq", "alt"):
        return node[1]
    return [node[2]] if node[0] == "group" else [node[1]] if node[0] == "rep" else []


def zero_width(node):
    """True for nodes that match a position, not a character: anchors, lookarounds."""
    return node[0] == "anchor" or node[0] == "group" and node[1] in LOOKAROUND


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
        return node[2]
    if kind == "seq":
        items = [x for x in node[1] if not zero_width(x)]
        return bool(items) and edge_is_word(items[-1 if at_end else 0], at_end)
    if kind == "group" and node[1] in LOOKAROUND:
        return False
    return any(edge_is_word(c, at_end) for c in children(node))


# --------------------------------------------------------------------------
# Regex writing: turns a parsed tree back into a Vim very magic regex. The
# converter writes every pattern as /\v.../ because very magic is closest to
# Oniguruma: ( ) | + ? { work without backslashes.
#   e.g. tree of "0x[0-9a-fA-F]+" -> 0x[0-9a-fA-F]+
#        tree of "a{2,}?"         -> a{-2,}
#        tree of "(?<=\.)\w"      -> %(\.)@<=\w
# --------------------------------------------------------------------------


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


def render(node):
    """Writes a tree node (and everything under it) as very magic text."""
    kind = node[0]
    if kind == "seq":
        return "".join(map(render, node[1]))
    if kind == "alt":
        return "|".join(map(render, node[1]))
    if kind == "group":
        # every group opens with %( (non-capturing); GROUPS gave the closer
        return "%(" + render(node[2]) + node[1]
    if kind == "rep":
        return render(node[1]) + quantifier(*node[2:])
    if kind == "char":
        c = node[1]
        if c in WORD or c == " " or ord(c) > 127:
            return c
        # tab/newline -> \t \n, other ASCII punctuation -> backslash + char
        return VIM_CONTROL.get(c, "\\" + c)
    if kind == "esc":
        return ESC[node[1]]
    # class, anchor and any already hold their Vim text
    return node[1]


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

    A scope can be several names separated by spaces; the last one is the most
    specific, so it is tried first.
      "constant.numeric.decimal.rascript" -> "Number"
      "meta.something.rascript"           -> None
    """
    for s in reversed((scope or "").split()):
        parts = s.split(".")
        for n in range(len(parts), 0, -1):
            if ".".join(parts[:n]) in SCOPE_MAP:
                return SCOPE_MAP[".".join(parts[:n])]
    return None


def is_rule(node):
    return "match" in node or "begin" in node


def camel(key):
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", key) if w)


class Converter:
    def __init__(self, grammar):
        self.grammar = grammar
        self.lang = grammar.get("scopeName", "source.tmlang").split(".")[-1]
        self.repository = grammar.get("repository", {})
        self.top_patterns = grammar.get("patterns", [])
        self.top_name = self.lang + "Top"
        self.group_names, self.rule_labels = {}, {}
        self.highlight_links = []  # (rule group, Vim group) pairs for highlight lines

    def assign(self, node, base, label):
        """Names each rule after its repository key and position."""
        if "include" in node:
            return
        nested = is_rule(node)
        if nested:
            name, n = base, 2
            while name in self.group_names.values():
                name, n = f"{base}{n}", n + 1
            self.group_names[id(node)], self.rule_labels[id(node)], base = name, label, name
        inline = [p for p in node.get("patterns", []) if "include" not in p]
        for i, p in enumerate(inline):
            single = len(inline) == 1 and not nested
            self.assign(p, base if single else f"{base}_{i + 1}", f"{label}/{i + 1}")

    def resolve(self, include):
        if include.startswith("#") and include[1:] in self.repository:
            return include[1:]
        raise ConvertError(f"unsupported include {include!r}")

    def walk(self, pats, visit, seen):
        """Calls visit on every rule matched by a pattern list, following includes."""
        for p in pats:
            if "include" in p:
                key = self.resolve(p["include"])
                if key in seen:
                    continue
                seen.add(key)
                entry = self.repository[key]
                if is_rule(entry):
                    visit(entry)
                else:
                    self.walk(entry.get("patterns", []), visit, seen)
            elif is_rule(p):
                visit(p)
            else:
                self.walk(p.get("patterns", []), visit, seen)

    def link(self, group, scope):
        """Records that a rule's group should be colored like its scope."""
        vim = scope_to_vim(scope)
        if vim:
            self.highlight_links.append((group, vim))

    @staticmethod
    def parse_rule(regex, label):
        """parse() with the rule's location added to any error message."""
        try:
            return parse(regex)
        except ConvertError as e:
            raise ConvertError(f"{label}: {e} in {regex!r}") from None

    @staticmethod
    def pattern(node, icase):
        r"""Wraps a tree as a Vim pattern: /\v.../, with \c if case-insensitive."""
        return "/\\v" + "\\c" * icase + render(node) + "/"

    def emit_match(self, rule, g, label):
        """A match rule -> one syntax match line."""
        node, icase, _ = self.parse_rule(rule["match"], label)
        self.link(g, rule.get("name"))
        return [f"syntax match {g} {self.pattern(node, icase)}"]

    def emit_region(self, rule, g, label):
        """A begin/end rule -> one syntax region line.

        e.g. strings: syntax region rascriptStrings matchgroup=rascriptStrings_begin
             start=/\v\"/ matchgroup=rascriptStrings_end end=/\v\"/
        matchgroup= puts the begin and end text in their own groups ({g}_begin,
        {g}_end) so they can be colored separately from the body, and so the
        region's contents are never matched inside them.
        """
        unsupported = {"while", "applyEndPatternLast"} & rule.keys()
        if unsupported:
            raise ConvertError(f"{label}: {', '.join(unsupported)} is not supported")
        name = rule.get("name")
        begin = self.pattern(*self.parse_rule(rule["begin"], label + " begin")[:2])
        self.link(g + "_begin", name)
        end = self.pattern(*self.parse_rule(rule["end"], label + " end")[:2])
        self.link(g + "_end", name)
        # contentName colors only the body; name colors begin, body and end
        self.link(g, rule.get("contentName") or name)
        return [f"syntax region {g} matchgroup={g}_begin start={begin} matchgroup={g}_end end={end}"]

    def convert(self):
        for key, entry in self.repository.items():
            self.assign(entry, self.lang + camel(key), "#" + key)
        self.assign({"patterns": self.top_patterns}, self.top_name, "patterns")

        order = []
        self.walk(self.top_patterns, order.append, set())
        # When several rules could match at the same spot, TextMate uses the
        # first one in the grammar but Vim uses the last one defined. Writing
        # the rules in reverse makes Vim pick the same rule VS Code does, e.g.
        # "if" is a control keyword, not the catch-all variable rule
        rules_out = []
        for rule in reversed(order):
            g, label = self.group_names[id(rule)], self.rule_labels[id(rule)]
            emit = self.emit_match if "match" in rule else self.emit_region
            rules_out += [f'" {label}'] + emit(rule, g, label)

        version = self.grammar.get("version")
        out = ['" Vim syntax file',
               f'" Language:    {self.grammar.get("name", self.lang)}',
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
                "syntax iskeyword @,48-57,_,192-255", "syntax sync fromstart", ""]
        out += ['" Rules: later definitions take priority'] + rules_out + [""]
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
    if len(sys.argv) != 2:
        sys.exit("usage: tmlanguage2vim.py INPUT.tmLanguage.json")
    with open(sys.argv[1], encoding="utf-8") as f:
        grammar = json.load(f)
    try:
        result = Converter(grammar).convert()
    except ConvertError as e:
        sys.exit(f"error: {e}")
    sys.stdout.write(result)


if __name__ == "__main__":
    main()
