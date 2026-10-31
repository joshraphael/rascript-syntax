# What the converters from a TextMate grammar (tmlanguage2*.py) have in common:
# parsing the grammar's regexes into a tree and writing a tree back out as a
# regex for another engine, through a dialect.
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

import re


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
