#!/usr/bin/env python3

import datetime
import json
import os
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
#   ("class", vim)                  a [...] class, already in Vim syntax
#   ("anchor", vim)                 ^ or $, stored as its Vim text
#   ("any", ".")                    . (any character)
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
    r"""Translates a [...] class token into a ("class", vim) node.

    Reads the inside one item at a time, where an item is a character or an
    escape, optionally followed by -character for a range (a-z). \w \d \s \h
    expand through CLASS_ESC; other items are kept, with ] ^ - \ escaped
    because those are the only characters special inside Vim's brackets.

    Examples (token -> returned node):
      r"[a-zA-Z_]"   -> ("class", r"[a-zA-Z_]")              nothing to change
      r"[\w-]"       -> ("class", r"[0-9A-Za-z_\-]")         \w expanded, - escaped
      r'[^\s"]'      -> ("class", r'[^ \t\r\n\d11\d12"]')    \s expanded, ^ kept
      r"[\.\]a-z^]"  -> ("class", r"[.\]a-z\^]")             \. unescaped, ] ^ escaped
      r"[[:alpha:]]" -> raises ConvertError
    """
    # "[^\s"a-z]" -> negated = True
    negated = token.startswith("[^")
    if "[:" in token:
        raise ConvertError("POSIX character classes are not supported")
    parts = []
    # split the inside into (lo, hi) items, hi set only for ranges like a-z;
    # lo/hi are one char or a backslash escape, and a - with nothing after it
    # is a literal dash. e.g. inside of [^\s"a-z] is \s"a-z -> (\s, ""), (", ""), (a, z)
    for lo, hi in re.findall(r"(\\.|[^\\])(?:-(\\.|[^\\]))?", token[1 + negated:-1]):
        # "\s" -> " \t\r\n\d11\d12"
        if lo[0] == "\\" and lo[1] in CLASS_ESC and not hi:
            parts.append(CLASS_ESC[lo[1]])
            continue
        # one character, or two for a range: '"' -> ['"'], "a"-"z" -> ["a", "z"],
        # "\." -> ["."], "\t" -> [real tab]
        chars = [escape_char(x[1]) if x[0] == "\\" else x for x in (lo, hi) if x]
        # back to Vim text: ["a", "z"] -> "a-z", [real tab] -> "\t", ["]"] -> "\]"
        parts.append("-".join(VIM_CONTROL.get(c, "\\" + c if c in "]^-\\" else c) for c in chars))
    # -> "[^ \t\r\n\d11\d12"a-z]"
    return ("class", "[" + "^" * negated + "".join(parts) + "]")


def is_rule(node):
    return "match" in node or "begin" in node


def camel(key):
    return "".join(w[:1].upper() + w[1:] for w in re.split(r"[^0-9A-Za-z]+", key) if w)


class Converter:
    def __init__(self, grammar, source_name):
        self.g, self.source_name = grammar, source_name
        self.lang = grammar.get("scopeName", "source.tmlang").split(".")[-1]
        self.repo, self.root = grammar.get("repository", {}), grammar.get("patterns", [])
        self.top = self.lang + "Top"
        self.names, self.labels = {}, {}

    def assign(self, node, base, label):
        """Names each rule after its repository key and position."""
        if "include" in node:
            return
        nested = is_rule(node)
        if nested:
            name, n = base, 2
            while name in self.names.values():
                name, n = f"{base}{n}", n + 1
            self.names[id(node)], self.labels[id(node)], base = name, label, name
        inline = [p for p in node.get("patterns", []) if "include" not in p]
        for i, p in enumerate(inline):
            single = len(inline) == 1 and not nested
            self.assign(p, base if single else f"{base}_{i + 1}", f"{label}/{i + 1}")

    def resolve(self, include):
        if include.startswith("#") and include[1:] in self.repo:
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
                entry = self.repo[key]
                if is_rule(entry):
                    visit(entry)
                else:
                    self.walk(entry.get("patterns", []), visit, seen)
            elif is_rule(p):
                visit(p)
            else:
                self.walk(p.get("patterns", []), visit, seen)

    def convert(self):
        for key, entry in self.repo.items():
            self.assign(entry, self.lang + camel(key), "#" + key)
        self.assign({"patterns": self.root}, self.top, "patterns")

        order = []
        self.walk(self.root, order.append, set())
        for rule in order:
            for key in ("match", "begin", "end"):
                if key in rule:
                    label = self.labels[id(rule)] + ("" if key == "match" else " " + key)
                    try:
                        parse(rule[key])
                    except ConvertError as e:
                        raise ConvertError(f"{label}: {e} in {rule[key]!r}") from None
        rules_out = [f'" {self.labels[id(rule)]}: {self.names[id(rule)]}' for rule in order]

        version = self.g.get("version")
        out = ['" Vim syntax file',
               f'" Language:    {self.g.get("name", self.lang)}',
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
        out += ['" Rules'] + rules_out + [""]
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
        result = Converter(grammar, os.path.basename(sys.argv[1])).convert()
    except ConvertError as e:
        sys.exit(f"error: {e}")
    sys.stdout.write(result)


if __name__ == "__main__":
    main()
