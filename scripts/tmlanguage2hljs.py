#!/usr/bin/env python3

# Converts a TextMate grammar into a highlight.js language (rascript.js).
# highlight.js modes work like TextMate rules: a match rule is a mode with
# match, a begin/end rule one with begin and end, and patterns are its
# contains. A TextMate capture is a part of a multi-part match instead
# (match: [/a/, /b/] with scope: { 2: ... }), so a regex with named captures
# is split into parts at them (see tmgrammar.Regex.split).
#
# Regex and rule support: see tmgrammar.py. Also unsupported (error) in
# highlight.js:
#   contentName (a mode's scope covers its begin, body and end alike)
#   (?i), and atomic groups (?>x): JavaScript has neither
#   a named capture that isn't one of the regex's top-level items (see split)
#   a pattern list that includes $self along with other patterns, except as
#     the last pattern of a repository entry (it is pushed in at the end)
#   scopes missing from SCOPES

import tmgrammar
from tmgrammar import SELF, ConvertError

# --------------------------------------------------------------------------
# Regex writing: highlight.js compiles regexes with the m and u flags
# (unicodeRegex), so this is the JavaScript spelling for those:
#   \w  [\p{L}\p{M}\p{N}\p{Pc}], and \b a lookaround on it: JavaScript's \w
#       and \b are ASCII only, Oniguruma's are Unicode
#   \s  [^\S\r\n] outside a class: TextMate matches one line at a time, but
#       highlight.js matches the whole text, where \s* could run on into the
#       next line (inside a class \s stays, e.g. [^\s(])
#   \h  [0-9a-fA-F]: JavaScript has no \h
#   a backslash only before syntax characters, and before /, which ends the
#       regex literal: the u flag rejects other escapes like \- outside a
#       class or \"
#   e.g. tree of "\b0x\h+\b" -> <\b>0x[0-9a-fA-F]+<\b>, <\b> being WORDB
# --------------------------------------------------------------------------

# the class items for a Unicode word character, the same set as Oniguruma's \w
WORD = r"\p{L}\p{M}\p{N}\p{Pc}"

# \b: a word character on one side and not the other
WORDB = f"(?:(?<=[{WORD}])(?![{WORD}])|(?<![{WORD}])(?=[{WORD}]))"

# escape letter -> its spelling outside a class (missing ones stay as they are)
ESCAPES = {"w": f"[{WORD}]", "W": f"[^{WORD}]", "s": r"[^\S\r\n]", "h": "[0-9a-fA-F]", "H": "[^0-9a-fA-F]"}

# escape letter -> its spelling inside a class
CLASS_ESCAPES = {"w": WORD, "h": "0-9a-fA-F"}


class JavaScript(tmgrammar.Oniguruma):
    def group(self, kind, inner):
        if kind == "(?>":
            raise ConvertError("atomic groups (?>x) are not supported")
        return super().group(kind, inner)

    def char(self, c):
        return tmgrammar.ONIG_CONTROL.get(c, "\\" + c if c in "\\^$.|?*+()[]{}/" else c)

    def esc(self, c):
        return ESCAPES.get(c, "\\" + c)

    def char_class(self, node):
        _, negated, items = node
        parts = [CLASS_ESCAPES.get(i[1], "\\" + i[1]) if i[0] == "esc" else
                 "-".join(tmgrammar.ONIG_CONTROL.get(c, "\\" + c if c in "\\]^-[/" else c) for c in i[1:])
                 for i in items]
        return "[" + "^" * negated + "".join(parts) + "]"

    def wordb(self, node):
        return WORDB


JAVASCRIPT = JavaScript()


def literal(node, label):
    """A tree -> its regex literal, /.../."""
    try:
        return "/" + tmgrammar.render(node, JAVASCRIPT) + "/"
    except ConvertError as e:
        raise ConvertError(f"{label}: {e}") from None


# --------------------------------------------------------------------------
# Scopes: each TextMate scope maps to a highlight.js scope (see
# https://highlightjs.readthedocs.io/en/latest/css-classes-reference.html)
# and a relevance, which highlightAuto adds up to guess a file's language. A
# mode's relevance is the highest of the scopes in its name and captures. The
# longest scope prefix that matches wins (see tmgrammar.scope_lookup).
# --------------------------------------------------------------------------

SCOPES = {
    "variable.other": ("variable", 0),
    "keyword.control": ("keyword", 0),
    "variable.language.this": ("variable.language", 0),
    "constant.language.boolean": ("literal", 0),
    "constant.numeric.decimal": ("number", 0),
    "constant.numeric.hexadecimal": ("number", 0),
    "keyword.class": ("keyword", 0),
    "entity.name.class": ("title.class", 0),
    "keyword.function": ("keyword", 0),
    "entity.name.function": ("title.function", 0),
    "entity.name.function.call": ("title.function.invoke", 0),
    "string.quoted.double": ("string", 0),
    "comment.line.double-slash": ("comment", 0), "punctuation.definition.comment.single": ("comment", 0),
    "comment.block": ("comment", 0), "punctuation.definition.comment.block": ("comment", 0),
    "keyword.other.id": ("keyword", 0),
    "constant.numeric.id": ("number", 0),
    "keyword.other.version": ("keyword", 0),
    "constant.numeric.version": ("number", 0),
    "punctuation.definition.template-expression": ("template-variable", 0),
    "constant.character.escape": ("char.escape", 0),
    "variable.other.assignment": ("variable", 0),
    "variable.parameter": ("params", 0),
    # built-in calls are what tell RAScript apart from JavaScript, so
    # highlightAuto picks RAScript for a file that has them
    "support.function": ("built_in", 10),
    "variable.parameter.function-call": ("attr", 0),
}


def constant(key):
    """A repository key -> its constant's name: function-names -> FUNCTION_NAMES."""
    return key.upper().replace("-", "_")


# --------------------------------------------------------------------------
# Writing the modes
# --------------------------------------------------------------------------

def scope_map(scopes):
    """{part number: scope} -> { 1: 'keyword', 3: 'title.function' }."""
    return "{ " + ", ".join(f"{n}: '{s}'" for n, s in sorted(scopes.items())) + " }"


class Converter:
    def __init__(self, grammar):
        self.grammar = grammar
        # the constant $self stands for: the one the top-level patterns include
        top = grammar.patterns.patterns
        self.statements = constant(top[0].target) if len(top) == 1 and top[0].kind == "include" else None

    def lookup(self, scope, label):
        """A TextMate scope -> (highlight.js scope, relevance), or (None, 0)
        for no scope."""
        return tmgrammar.lookup(SCOPES, scope, label, "highlight.js scope") or (None, 0)

    def scope(self, scope, label):
        return self.lookup(scope, label)[0]

    def relevance(self, rule):
        """The highest relevance of the scopes in a rule's name and captures."""
        scopes = [(rule.name, rule.label)] + [
            (cap.get("name"), f"{rule.label} {key} {n}")
            for key in ("captures", "beginCaptures", "endCaptures") for n, cap in rule.raw.get(key, {}).items()]
        return max(self.lookup(s, label)[1] for s, label in scopes)

    def ref(self, node):
        """An include -> the constant it refers to."""
        if node.target != SELF:
            return constant(node.target)
        if not self.statements:
            raise ConvertError(f"{node.label}: $self needs the top-level patterns to be a single include")
        return self.statements

    def quoted(self, scope, outer):
        """A highlight.js scope -> 'scope', or None for none or one the same
        as outer: the mode's own scope, which its span already gives."""
        return f"'{scope}'" if scope and scope != outer else None

    def parts(self, regex, name, outer):
        r"""A regex and its captures -> (regex text, scope text or None).

        name is the TextMate scope of the text the captures don't cover (a
        match rule's name; None for begin and end, which the mode's own scope
        covers). outer is the mode's own highlight.js scope.

        With no named captures, or only ones covering the whole match, the
        regex is written as it is, with the whole match's scope (see
        Regex.whole_scope). Otherwise it is split into parts at its named
        captures (see Regex.split), and written as an array with a
        { part number: scope } map; a split with only one part is the whole
        match again:
          \b(if)[\t ]*\(  -> [/<\b>if/, /[\t ]*\(/], { 1: 'keyword' }
        """
        named = [k for k, cap in regex.captures.items()
                 if k != "0" and cap.get("name") and int(k) not in regex.whole_groups]
        if not named:
            scope = self.scope(regex.whole_scope(name), regex.label)
            return literal(regex.tree, regex.label), self.quoted(scope, outer)
        parts = regex.split()
        if len(parts) == 1:
            node, key = parts[0]
            scope = self.scope(regex.captures[key]["name"], f"{regex.label} capture {key}")
            return literal(node, regex.label), self.quoted(scope, outer)
        between = self.scope(name, regex.label)
        scopes = {}
        for n, (node, key) in enumerate(parts, 1):
            scope = self.scope(regex.captures[key]["name"], f"{regex.label} capture {key}") if key else between
            if scope and scope != outer:
                scopes[n] = scope
        text = "[" + ", ".join(literal(node, regex.label) for node, _ in parts) + "]"
        return text, scope_map(scopes) if scopes else None

    def mode(self, rule, depth):
        """A match or begin/end rule -> its mode's lines, at depth levels of
        indentation, with the rule's comment above it."""
        if rule.content_name:
            raise ConvertError(f"{rule.label}: contentName is not supported")
        regexes = [("match", rule.match)] if rule.kind == "match" else [("begin", rule.begin), ("end", rule.end)]
        for _, regex in regexes:
            if regex.icase:
                raise ConvertError(f"{regex.label}: (?i) is not supported")
        lines = []
        if rule.kind == "match":
            text, scope = self.parts(rule.match, rule.name, None)
            lines += [f"scope: {scope},"] * bool(scope) + [f"match: {text},"]
        else:
            name = self.scope(rule.name, rule.label)
            if name:
                lines.append(f"scope: '{name}',")
            for key, regex in regexes:
                text, scope = self.parts(regex, None, name)
                lines += [f"{key}: {text},"] + [f"{key}Scope: {scope},"] * bool(scope)
            lines += self.contains(rule.patterns)
        lines.append(f"relevance: {self.relevance(rule)}")
        pad = "    " * depth
        return ([f"{pad}// {rule.comment}"] * bool(rule.comment) + [pad + "{"]
                + [pad + "    " + line for line in lines] + [pad + "}"])

    def contains(self, patterns):
        """A rule's patterns -> its contains: lines, or none for no patterns.
        A single include is a reference to its constant (contains: STATEMENTS);
        anything else is a list of modes, with includes spread into it."""
        if not patterns:
            return []
        if len(patterns) == 1 and patterns[0].kind == "include":
            return [f"contains: {self.ref(patterns[0])},"]
        return ["contains: ["] + self.modes(patterns, 1) + ["],"]

    def modes(self, patterns, depth):
        """A pattern list -> the lines of its modes, at depth, separated by
        commas. An include is spread (...COMMENTS); STATEMENTS is still empty
        while the constants are written, so spreading it is an error here (see
        entry)."""
        pad = "    " * depth
        out = []
        for p in patterns:
            if out:
                out[-1] += ","
            if p.kind == "include":
                if self.ref(p) == self.statements:
                    raise ConvertError(f"{p.label}: $self can only be included alone, or last in a repository entry")
                out += [f"{pad}// {p.comment}"] * bool(p.comment) + [f"{pad}...{self.ref(p)}"]
            elif p.is_rule:
                out += self.mode(p, depth)
            else:
                raise ConvertError(f"{p.label}: a pattern list inside a pattern list is not supported")
        return out

    def entry(self, key):
        """A repository entry -> (its constant's modes, and whether it ends by
        including STATEMENTS, which is then pushed in once STATEMENTS is
        filled). A single rule's comment goes above the constant, not the mode."""
        entry = self.grammar.repository[key]
        if entry.is_rule:
            return self.mode(entry, 2)[bool(entry.comment):], False
        patterns = entry.patterns
        spread = bool(patterns) and patterns[-1].kind == "include" and self.ref(patterns[-1]) == self.statements
        return self.modes(patterns[:len(patterns) - spread], 2), spread
