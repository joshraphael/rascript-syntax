# What the converters from a TextMate grammar (tmlanguage2*.py) have in common:
# reading the grammar into rules and includes, parsing its regexes into a tree,
# and writing a tree back out as a regex for another engine, through a dialect.
#
# Rule support. Supported: match rules, begin/end rules, name, contentName,
# captures, beginCaptures and endCaptures with names, patterns, repository,
# and includes of #key, $self and $base. comment is allowed anywhere, and
# top-level metadata (version, fileTypes, uuid, ...) is ignored.
# Unsupported (error):
#   while and applyEndPatternLast, and a begin rule with no end
#   captures with their own patterns, or for groups that don't exist
#   includes of other grammars (source.js) or of unknown repository keys
#   any other key, e.g. injections, disabled, or a repository nested inside
#     a rule (see GRAMMAR_KEYS, RULE_KEYS and CAPTURE_KEYS)
# A converter can support less; its own limits are listed at its top.
#
# Regex support. Grammar regexes use Oniguruma syntax; this is what parse()
# understands. Anything unsupported stops the build with an error naming the rule.
#
# Supported:
#   literal characters, including non-ASCII (é, emoji)
#   escaped punctuation      \. \( \/ \" \- \  ...
#   control characters       \t \n \r
#   character sets           \w \W \s \S \d \D \h \H
#   word boundary            \b
#   any character, anchors   .  ^  $
#   classes                  [abc] [^abc] [a-z] []a] [a-], containing literal
#                            or escaped characters, \t \n \r and \w \s \d \h
#   alternation              a|b, including empty branches
#   groups                   (x) (?:x) (?>x)
#   lookarounds              (?=x) (?!x) (?<=x) (?<!x)
#   repeats                  * + ? {n} {n,} {n,m}, and lazy *? +? ?? {n,m}?
#   case-insensitive         (?i), only at the very start of the regex
#
# Unsupported (error):
#   (?i) anywhere else, other flags and flag groups: (?m) (?x) (?i:x) (?-i)
#   named groups, back-references and subexpression calls:
#     (?<name>x) (?'name'x) \1 \k<name> \g<name>
#   comment groups (?#...), absent groups (?~x), conditionals (?(1)x|y)
#   escaped letters/digits not listed above, e.g. \A \z \Z \G \K \B \R \X
#     \y \Y \a \e \f \v \0 \xHH \x{H} \uHHHH \o{...} \cX \C-x \M-x \p{L} \P{L}
#   inside a class: \W \S \D \H \b \xHH \p{L} ..., POSIX classes [[:alpha:]],
#     nested classes [a[b]] and intersections [a-z&&[^x]]
#   repeats: {,n} (write {0,n}), possessive *+ ++ ?+ {n,m}+, a repeat of a
#     repeat (a** a{1,2}{2}), a repeat with nothing before it (*a {1})
#   unbalanced parentheses

import argparse
import json
import re
import sys


class ConvertError(Exception):
    pass


# --------------------------------------------------------------------------
# Regex parsing: turns an Oniguruma regex string into a tree of tuples that
# holds what the regex means in Oniguruma, not how any editor writes it.
# Each node is a tuple whose first item names its type; the rest are its
# fields, read by position (node[1], node[2], ...):
#   ("seq", items)                  items: nodes matched one after another
#   ("alt", branches)               branches: nodes, any one may match (a|b)
#   ("group", kind, child, index)   ( ) group; kind: its opener from
#                                   GROUP_KINDS, e.g. "(?="; index: capture
#                                   number or None
#   ("rep", child, lo, hi, lazy)    child repeated lo..hi times (hi None =
#                                   no limit); from * + ? {n,m}
#   ("char", c)                     one literal character
#   ("esc", c)                      escape letter from ESCAPES, e.g. "d"
#   ("class", negated, items)       a [...] class; items are ("char", c),
#                                   ("range", lo, hi) with lo/hi characters,
#                                   and ("esc", c) with c from CLASS_ESCAPES
#   ("anchor", c)                   ^ or $
#   ("any",)                        . (any character)
#   ("wordb",)                      \b (word boundary)
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

# The group openers the parser supports:
#   (x)     capture group
#   (?:x)   non-capturing group
#   (?>x)   atomic group
#   (?=x)   lookahead           x must follow
#   (?!x)   negative lookahead  x must not follow
#   (?<=x)  lookbehind          x must come before
#   (?<!x)  negative lookbehind x must not come before
GROUP_KINDS = ("(", "(?:", "(?>", "(?=", "(?!", "(?<=", "(?<!")

# The lookaround openers. Lookarounds check text without consuming it, so they
# don't count as a neighbouring character
LOOKAROUND = ("(?=", "(?!", "(?<=", "(?<!")

# The escape letters for sets of characters. Uppercase is the opposite set
# (\W = any non-word character). Escaped letters not listed here or in CONTROL
# are an error (see escape_char).
#   \w  word character: letter, digit or _
#   \s  whitespace: space, tab, newline ...
#   \d  digit 0-9
#   \h  hex digit 0-9 a-f A-F
ESCAPES = "wWsSdDhH"

# The escape letters allowed inside a [...] class: \w \d \s \h
CLASS_ESCAPES = "wdsh"

# Maps an escape letter for an invisible character -> that actual character,
# e.g. "t" -> a real tab. The parser stores \t \n \r as plain ("char", c)
# nodes, the same as a typed letter:
#   \t  tab
#   \n  newline
#   \r  carriage return
CONTROL = {"t": "\t", "n": "\n", "r": "\r"}


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
            elif t in GROUP_KINDS:
                index = None
                if t == "(":
                    count[0] += 1
                    index = count[0]
                child = alt()
                if not toks or toks.pop() != ")":
                    raise ConvertError("missing ')'")
                items.append(("group", t, child, index))
            elif t.startswith("[") and len(t) > 1:
                items.append(char_class(t))
            elif t in ("^", "$"):
                items.append(("anchor", t))
            elif t == ".":
                items.append(("any",))
            elif t == r"\b":
                items.append(("wordb",))
            elif t[0] == "\\" and t[1:] in ESCAPES:
                items.append(("esc", t[1]))
            elif t[0] == "\\":
                items.append(("char", escape_char(t[1])))
            elif t.startswith("(?"):
                raise ConvertError(f"unsupported group {t!r}")
            elif t == "{" and re.match(r",\d+\}", "".join(reversed(toks))):
                # Oniguruma reads {,n} as "0 to n" repeats; QUANTIFIER_PARTS
                # doesn't, so it would become the literal text {,n}
                raise ConvertError("{,n} repeats are not supported, use {0,n}")
            else:
                items.append(("char", t))
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
    r"""Parses a [...] class token into a ("class", negated, items) node.

    Reads the inside one item at a time, where an item is a character or an
    escape, optionally followed by -character for a range (a-z). \w \d \s \h
    become ("esc", c) items; escaped characters are stored without their
    backslash.

    Examples (token -> returned node):
      r"[a-z_]"      -> ("class", False, [("range", "a", "z"), ("char", "_")])
      r'[^\s"]'      -> ("class", True, [("esc", "s"), ("char", '"')])
      r"[\.\]]"      -> ("class", False, [("char", "."), ("char", "]")])
      r"[[:alpha:]]" -> raises ConvertError
      r"[a[b]"       -> raises ConvertError   (from [a[b]], a nested class)
      r"[a-z&&[^x]"  -> raises ConvertError   (from [a-z&&[^x]], an intersection)
    """
    # "[^\s"a-z]" -> negated = True
    negated = token.startswith("[^")
    if "[:" in token:
        raise ConvertError("POSIX character classes are not supported")
    # Oniguruma allows classes inside classes ([a[b]]) and intersections
    # ([a-z&&[^x]]); TOKEN ends the class at the first ], so these would be
    # split in the wrong place. An escaped \[ or \& is a plain character.
    units = re.findall(r"\\.|.", token[1 + negated:-1], re.S)
    if "&&" in "".join(u if u == "&" else " " for u in units):
        raise ConvertError("character class intersections (&&) are not supported")
    if "[" in units:
        raise ConvertError("nested character classes are not supported")
    items = []
    # split the inside into (lo, hi) items, hi set only for ranges like a-z;
    # lo/hi are one char or a backslash escape, and a - with nothing after it
    # is a literal dash. e.g. inside of [^\s"a-z] is \s"a-z -> (\s, ""), (", ""), (a, z)
    for lo, hi in re.findall(r"(\\.|[^\\])(?:-(\\.|[^\\]))?", token[1 + negated:-1]):
        if lo[0] == "\\" and lo[1] in CLASS_ESCAPES and not hi:
            items.append(("esc", lo[1]))
            continue
        # "\." -> ".", "\t" -> real tab
        chars = [escape_char(x[1]) if x[0] == "\\" else x for x in (lo, hi) if x]
        items.append(("range", *chars) if hi else ("char", chars[0]))
    return ("class", negated, items)


def children(node):
    """The nodes directly inside a node (none for single characters)."""
    if node[0] in ("seq", "alt"):
        return node[1]
    return [node[2]] if node[0] == "group" else [node[1]] if node[0] == "rep" else []


def zero_width(node):
    """True for nodes that match a position, not a character: anchors, \\b, lookarounds."""
    return node[0] in ("anchor", "wordb") or node[0] == "group" and node[1] in LOOKAROUND


def capture_path(root, target):
    """The ids of every node on the way from root down to capture group
    target, the group included."""
    path = set()

    def find(node):
        hit = node[0] == "group" and node[3] == target or any(find(c) for c in children(node))
        if hit:
            path.add(id(node))
        return hit

    if not find(root):
        raise ConvertError(f"capture group {target} does not exist")
    return path


def nesting(root, target):
    """What capture group target is inside, from the outside in, for errors:
    "in an alternation", "repeated", "in a lookaround" or "nested in another group"."""
    path, node = capture_path(root, target), root
    while not (node[0] == "group" and node[3] == target):
        if node[0] == "alt":
            return "in an alternation"
        if node[0] == "rep":
            return "repeated"
        if node[0] == "group":
            return "in a lookaround" if node[1] in LOOKAROUND else "nested in another group"
        node = next(c for c in children(node) if id(c) in path)
    return "at the top level"


# --------------------------------------------------------------------------
# Regex writing: render() walks a tree and a dialect says how each node is
# written for one regex engine. A converter subclasses Dialect and fills in
# the methods for the nodes its engine writes differently.
# --------------------------------------------------------------------------

class Dialect:
    """How to write each kind of tree node. Every method returns text."""

    def seq(self, items, parts):
        """items: the sequence's nodes; parts: each one already rendered."""
        return "".join(parts)

    def alt(self, parts):
        return "|".join(parts)

    def group(self, kind, inner):
        """kind: the group's opener from GROUP_KINDS; inner: the rendered contents."""
        raise NotImplementedError

    def quantifier(self, lo, hi, lazy):
        raise NotImplementedError

    def char(self, c):
        raise NotImplementedError

    def esc(self, c):
        raise NotImplementedError

    def char_class(self, node):
        raise NotImplementedError

    def anchor(self, c):
        raise NotImplementedError

    def any(self):
        raise NotImplementedError

    def wordb(self, node):
        raise NotImplementedError


def render(node, dialect):
    """Writes a tree node (and everything under it) through a dialect."""
    kind = node[0]
    if kind == "seq":
        return dialect.seq(node[1], [render(x, dialect) for x in node[1]])
    if kind == "alt":
        return dialect.alt([render(x, dialect) for x in node[1]])
    if kind == "group":
        return dialect.group(node[1], render(node[2], dialect))
    if kind == "rep":
        return render(node[1], dialect) + dialect.quantifier(*node[2:])
    if kind == "char":
        return dialect.char(node[1])
    if kind == "esc":
        return dialect.esc(node[1])
    if kind == "class":
        return dialect.char_class(node)
    if kind == "anchor":
        return dialect.anchor(node[1])
    if kind == "any":
        return dialect.any()
    return dialect.wordb(node)


# Oniguruma: writes a tree back as an Oniguruma regex, in one fixed spelling.
# Outside a class, punctuation that can be special gets a backslash, brackets
# and braces included (\] \{ \}); inside a class, only \ ] ^ - [ do. make test
# checks every regex in the grammar comes back unchanged, so the tree is known
# to hold everything the other dialects need, and the grammar keeps to this
# spelling.

# Maps an invisible character -> its escape, the reverse of CONTROL
ONIG_CONTROL = {c: "\\" + e for e, c in CONTROL.items()}


class Oniguruma(Dialect):
    def group(self, kind, inner):
        return kind + inner + ")"

    def quantifier(self, lo, hi, lazy):
        short = {(0, None): "*", (1, None): "+", (0, 1): "?"}.get((lo, hi))
        body = short or "{" + (str(lo) if lo == hi else f"{lo},{'' if hi is None else hi}") + "}"
        return body + "?" * lazy

    def char(self, c):
        return ONIG_CONTROL.get(c, "\\" + c if c in "\\^$.|?*+()[]{}" else c)

    def esc(self, c):
        return "\\" + c

    def char_class(self, node):
        _, negated, items = node
        parts = ["\\" + i[1] if i[0] == "esc" else "-".join(ONIG_CONTROL.get(c, "\\" + c if c in "\\]^-[" else c)
                                                           for c in i[1:]) for i in items]
        return "[" + "^" * negated + "".join(parts) + "]"

    def anchor(self, c):
        return c

    def any(self):
        return "."

    def wordb(self, node):
        return "\\b"


ONIGURUMA = Oniguruma()


# --------------------------------------------------------------------------
# Grammar reading: turns a TextMate grammar into Pattern nodes, one for each
# rule, include and plain pattern list, checking along the way that every key
# is one the converters handle. Regexes are parsed when a converter first asks
# for them, so a rule nothing reaches is never parsed.
# --------------------------------------------------------------------------

# What "$self" and "$base" includes resolve to: the grammar's top-level patterns
SELF = "$self"

# Keys the converters understand, so a grammar feature they don't handle is
# reported instead of silently dropped (e.g. injections, disabled, or a
# repository nested inside a rule). Top-level metadata that doesn't affect
# highlighting is allowed. while, applyEndPatternLast and capture patterns
# are listed so they reach their own, more specific errors later.
GRAMMAR_KEYS = {"$schema", "name", "scopeName", "version", "fileTypes", "firstLineMatch", "foldingStartMarker",
                "foldingStopMarker", "uuid", "information_for_contributors", "comment", "patterns", "repository"}
RULE_KEYS = {"comment", "name", "contentName", "match", "begin", "end", "captures", "beginCaptures",
             "endCaptures", "patterns", "include", "while", "applyEndPatternLast"}
CAPTURE_KEYS = {"comment", "name", "patterns"}


def check_keys(node, allowed, label):
    unknown = sorted(set(node) - allowed)
    if unknown:
        raise ConvertError(f"{label}: unsupported key{'s' * (len(unknown) > 1)} {', '.join(map(repr, unknown))}")


class Regex:
    """One parsed regex of a rule, with the captures that apply to it.

    tree, icase, ngroups: what parse() returned. captures: the grammar's
    {"1": {"name": ...}, ...} for this regex. label: where it is, for errors,
    e.g. "#function-names/1 begin".
    """

    def __init__(self, src, captures, label):
        try:
            self.tree, self.icase, self.ngroups = parse(src)
        except ConvertError as e:
            raise ConvertError(f"{label}: {e} in {src!r}") from None
        # checked here, before any converter writes a capture, so a grammar
        # mistake every converter shares is the first error from all of them
        for key, cap in sorted(captures.items(), key=lambda kv: int(kv[0])):
            # captures with their own patterns, or for groups that don't exist
            if "patterns" in cap or int(key) > self.ngroups:
                raise ConvertError(f"{label}: capture {key} is not supported")
        self.src, self.captures, self.label = src, captures, label

    @property
    def whole_groups(self):
        """The capture numbers of the groups around the entire regex.
          ((?:a|b))  -> groups 1 and the (?:) both wrap everything -> [1]
        """
        groups, n = [], self.tree
        while n[0] == "seq" and len(n[1]) == 1 or n[0] == "group" and n[1] in ("(", "(?:"):
            if n[0] == "group" and n[3]:
                groups.append(n[3])
            n = n[1][0] if n[0] == "seq" else n[2]
        return groups

    def whole_scope(self, name):
        r"""The scope of the whole match: the rule's name, unless a capture
        covers all of it, in which case the capture's name wins:
          capture "0"                       always the whole match
          a group around the entire regex   e.g. capture "1" of ([a-zA-Z_]\w*)
        """
        for key in ["0"] + [str(i) for i in self.whole_groups]:
            name = self.captures.get(key, {}).get("name", name)
        return name

    def split(self):
        r"""Splits the regex at its named captures, for engines that scope
        parts of a match instead of capture groups.

        Returns [(node, key)]: the parts in order, key being the capture's
        number for a part that is a named capture and None for the text
        between them. Capture 0 isn't split out (see whole_scope). A run of
        only zero-width items (\b ^ $ lookarounds) joins the capture after it,
        or else the one before it, so no part is empty:
          ^//[\t ]*(#ID)[\t ]*=[\t ]*(\d+)$
            -> ^//[\t ]*  #ID (1)  [\t ]*=[\t ]*  \d+$ (2)
          \b(for)[\t ]+(\b(?!\d)\w+)[\t ]+(in)\b
            -> \bfor (1)  [\t ]+  \b(?!\d)\w+ (2)  [\t ]+  in\b (3)
        A named capture has to be one of the regex's top-level items to be
        split out; one nested in another group, repeated, in an alternation or
        in a lookaround is an error.
        """
        named = {int(k) for k, cap in self.captures.items() if k != "0" and cap.get("name")}
        items = self.tree[1] if self.tree[0] == "seq" else [self.tree]
        # [items, key] runs: each named top-level capture alone, the rest grouped
        runs = []
        for item in items:
            if item[0] == "group" and item[3] in named:
                runs.append([[item[2]], str(item[3])])
            elif runs and runs[-1][1] is None:
                runs[-1][0].append(item)
            else:
                runs.append([[item], None])
        for key in sorted(named - {int(k) for _, k in runs if k}):
            raise ConvertError(f"{self.label}: capture {key} can't be split out of the regex: it is "
                               + nesting(self.tree, key))
        if len(runs) > 1:
            # move zero-width-only runs into a neighbouring capture
            for i in range(len(runs) - 1, -1, -1):
                items, key = runs[i]
                if key is None and all(zero_width(x) for x in items):
                    j = i + 1 if i + 1 < len(runs) and runs[i + 1][1] else i - 1 if i and runs[i - 1][1] else None
                    if j is not None:
                        runs[j][0] = items + runs[j][0] if j > i else runs[j][0] + items
                        del runs[i]
        parts = []
        for items, key in runs:
            # an alternation joined with other items needs a group around it: a|b\b -> (?:a|b)\b
            items = [("group", "(?:", x, None) if x[0] == "alt" and len(items) > 1 else x for x in items]
            parts.append((items[0] if len(items) == 1 else ("seq", items), key))
        return parts


class Pattern:
    """One entry of a grammar's pattern list, or a repository entry.

    kind is one of:
      "match"    a match rule
      "region"   a begin/end rule
      "include"  an include; include is its text, target what it resolves to
      "list"     only a list of patterns (a repository entry that groups rules,
                 or the grammar's top-level patterns)
    label says where it is, for errors and comments: "#key" for a repository
    entry, "patterns" for the top level, then "/n" for the nth rule inside
    (includes aren't counted), e.g. "#function-names/1".
    """

    def __init__(self, grammar, raw, label, checked=False):
        self.grammar, self.raw, self.label = grammar, raw, label
        if not checked:
            check_keys(raw, RULE_KEYS, label)
        for key in ("captures", "beginCaptures", "endCaptures"):
            for n, cap in raw.get(key, {}).items():
                check_keys(cap, CAPTURE_KEYS, f"{label} {key} {n}")
        for p in raw.get("patterns", []):
            if "include" in p:
                check_keys(p, RULE_KEYS, f"{label} include {p['include']}")
        self.comment, self.name, self.content_name = raw.get("comment"), raw.get("name"), raw.get("contentName")
        self.include = raw.get("include")
        self.kind = ("include" if "include" in raw else "match" if "match" in raw else
                     "region" if "begin" in raw else "list")
        self.patterns = []
        if self.kind == "include":
            return
        n = 0
        for p in raw.get("patterns", []):
            if "include" in p:
                self.patterns.append(Pattern(grammar, p, f"{label} include {p['include']}", checked=True))
            else:
                n += 1
                self.patterns.append(Pattern(grammar, p, f"{label}/{n}"))
        self._regexes = {}

    @property
    def is_rule(self):
        return self.kind in ("match", "region")

    @property
    def target(self):
        """An include -> a repository key, or SELF for the top-level patterns."""
        return self.grammar.resolve(self.include)

    def _regex(self, key, captures, label):
        if key not in self._regexes:
            self._regexes[key] = Regex(self.raw[key], captures, label)
        return self._regexes[key]

    @property
    def match(self):
        return self._regex("match", self.raw.get("captures", {}), self.label)

    def _check_region(self):
        unsupported = {"while", "applyEndPatternLast"} & self.raw.keys()
        if unsupported:
            raise ConvertError(f"{self.label}: {', '.join(unsupported)} is not supported")
        if "end" not in self.raw:
            raise ConvertError(f"{self.label}: begin without end is not supported")

    # "captures" applies to both begin and end unless they have their own
    @property
    def begin(self):
        self._check_region()
        return self._regex("begin", self.raw.get("beginCaptures", self.raw.get("captures", {})), self.label + " begin")

    @property
    def end(self):
        self._check_region()
        return self._regex("end", self.raw.get("endCaptures", self.raw.get("captures", {})), self.label + " end")


class Grammar:
    """A TextMate grammar: its repository entries (in order) and top-level
    patterns as Pattern nodes, and its metadata in raw."""

    def __init__(self, raw):
        check_keys(raw, GRAMMAR_KEYS, "grammar")
        self.raw = raw
        self.repository = {key: Pattern(self, entry, "#" + key) for key, entry in raw.get("repository", {}).items()}
        self.patterns = Pattern(self, {"patterns": raw.get("patterns", [])}, "patterns")

    def resolve(self, include):
        """An include's text -> a repository key, or SELF for the top-level patterns."""
        if include in ("$self", "$base"):
            return SELF
        if include.startswith("#") and include[1:] in self.repository:
            return include[1:]
        raise ConvertError(f"unsupported include {include!r}")

    def entry(self, key):
        """A repository key or SELF -> its Pattern."""
        return self.patterns if key == SELF else self.repository[key]

    def walk(self, patterns, visit, seen):
        """Calls visit on every rule matched by a pattern list, following
        includes. seen holds the keys already followed (each is followed once);
        afterwards it holds every key the walk included."""
        for p in patterns:
            if p.kind == "include":
                key = p.target
                if key in seen:
                    continue
                seen.add(key)
                entry = self.entry(key)
                if entry.is_rule:
                    visit(entry)
                else:
                    self.walk(entry.patterns, visit, seen)
            elif p.is_rule:
                visit(p)
            else:
                self.walk(p.patterns, visit, seen)


# --------------------------------------------------------------------------
# Scopes and the command line
# --------------------------------------------------------------------------

def scope_lookup(table, scope):
    """Returns what a table maps a scope to, by its longest listed prefix, or
    None if no prefix is in the table. e.g. with {"constant": "Constant",
    "constant.numeric": "Number"}:
      "constant.numeric.decimal.rascript" -> "Number"   (not "Constant": shorter)
      "meta.something.rascript"           -> None

    A scope can be several names separated by spaces; the last one is the most
    specific, so it is tried first.
    """
    for s in reversed((scope or "").split()):
        parts = s.split(".")
        for n in range(len(parts), 0, -1):
            if ".".join(parts[:n]) in table:
                return table[".".join(parts[:n])]
    return None


def main(description, convert):
    """A converter's command line: reads the grammar named on it, writes
    convert(Grammar) to stdout, and exits with "error: ..." on a ConvertError."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("grammar", help="TextMate grammar to convert (.tmLanguage.json)")
    args = parser.parse_args()
    with open(args.grammar, encoding="utf-8") as f:
        raw = json.load(f)
    try:
        result = convert(Grammar(raw))
    except ConvertError as e:
        sys.exit(f"error: {e}")
    sys.stdout.write(result)
