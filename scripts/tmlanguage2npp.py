#!/usr/bin/env python3

# Converts a TextMate grammar into the RAScript.xml that the npp-rascript
# Notepad++ plugin reads. The plugin works like the TextMate engine, so every
# rule, include and capture is written as it is in the grammar, in the same
# order, and every regex is the grammar's own apart from the spelling of \h.
#
# Regex and rule support: see tmgrammar.py. Also unsupported (error) in
# Notepad++:
#   contentName (the plugin colors a region's begin, body and end alike)
#   lookbehinds that can match text of different lengths, e.g. (?<=a|bc) or
#     (?<!a+): Boost only allows fixed-length lookbehinds
#   scopes missing from SCOPE_STYLES, except meta.* scopes, which get no style
#   comments containing --, which an XML comment can't hold

import tmgrammar
from tmgrammar import SELF, ConvertError, children, zero_width

# --------------------------------------------------------------------------
# Regex writing: the Oniguruma spelling (see tmgrammar.py), except for \h and
# \H, which Boost reads as horizontal whitespace, not as hex digits.
#   e.g. tree of "\b0x\h+\b" -> \b0x[0-9a-fA-F]+\b
# --------------------------------------------------------------------------

# \h inside a class, as the class items for 0-9a-fA-F
HEX = [("range", "0", "9"), ("range", "a", "f"), ("range", "A", "F")]


class Boost(tmgrammar.Oniguruma):
    def esc(self, c):
        return {"h": "[0-9a-fA-F]", "H": "[^0-9a-fA-F]"}.get(c, "\\" + c)

    def char_class(self, node):
        _, negated, items = node
        return super().char_class(("class", negated, [x for i in items for x in (HEX if i == ("esc", "h") else [i])]))


BOOST = Boost()


def width(node):
    r"""How many characters a node always matches, or None if that can vary.
      "a\.b" -> 3, "a|bc" -> None, "x{2}" -> 2, "\b" -> 0
    """
    kind = node[0]
    if zero_width(node):
        return 0
    if kind in ("char", "esc", "class", "any"):
        return 1
    if kind == "seq":
        widths = [width(x) for x in node[1]]
        return None if None in widths else sum(widths)
    if kind == "alt":
        widths = {width(x) for x in node[1]}
        return widths.pop() if len(widths) == 1 else None
    if kind == "group":
        return width(node[2])
    # a repeat: fixed only when it repeats a fixed width an exact number of times
    w = width(node[1])
    return None if w is None or node[2] != node[3] else w * node[2]


def check_lookbehinds(node, label):
    if node[0] == "group" and node[1] in ("(?<=", "(?<!") and width(node[2]) is None:
        raise ConvertError(f"{label}: lookbehinds that can match text of different lengths are not supported")
    for c in children(node):
        check_lookbehinds(c, label)


# --------------------------------------------------------------------------
# Styles: maps a TextMate scope -> the Notepad++ style IDs for the light and
# dark themes. The longest prefix that matches wins (see scope_lookup), e.g.
# "variable.other.assignment.rascript" -> (50, 51), not variable.other's (1, 2).
# --------------------------------------------------------------------------

SCOPE_STYLES = {
    "variable.other": (1, 2),
    "keyword.control": (3, 4),
    "variable.language.this": (5, 6),
    "constant.language.boolean": (7, 8),
    "constant.numeric.decimal": (9, 10),
    "constant.numeric.hexadecimal": (11, 12),
    "keyword.class": (13, 14),
    "entity.name.class": (15, 16),
    "keyword.function": (17, 18),
    "entity.name.function": (21, 22),
    "string.quoted.double": (23, 24),
    "comment.line.double-slash": (25, 26), "punctuation.definition.comment.single": (25, 26),
    "comment.block": (27, 28), "punctuation.definition.comment.block": (27, 28),
    "keyword.other.id": (29, 30),
    "constant.numeric.id": (40, 41),
    "keyword.other.version": (42, 43),
    "constant.numeric.version": (44, 45),
    "punctuation.definition.template-expression": (46, 47),
    "constant.character.escape": (48, 49),
    "variable.other.assignment": (50, 51),
    "variable.parameter": (52, 53),
    "support.function": (54, 55),
    "variable.parameter.function-call": (56, 57),
}

# Used instead of SCOPE_STYLES for the captures of a rule named
# meta.function-call: a function name there is a call, everywhere else a
# definition (FUNCTION-CALLS 19/20 vs FUNCTION-NAME 21/22)
CALL_STYLES = {
    "entity.name.function": (19, 20),
}


# --------------------------------------------------------------------------
# Writing the XML
# --------------------------------------------------------------------------

def attr(key, value):
    r"""Writes key="value", XML-escaped. A value containing " is quoted with '
    instead: begin='"'."""
    value = value.replace("&", "&amp;").replace("<", "&lt;")
    quote = "'" if '"' in value and "'" not in value else '"'
    if quote == '"':
        value = value.replace('"', "&quot;")
    return f" {key}={quote}{value}{quote}"


class Converter:
    def __init__(self, grammar):
        self.grammar = grammar

    def styles(self, scope, label, call=False):
        """A scope -> its lightStyle/darkStyle attributes, or "" for no style."""
        if not scope:
            return ""
        ids = call and tmgrammar.scope_lookup(CALL_STYLES, scope) or tmgrammar.scope_lookup(SCOPE_STYLES, scope)
        if ids is None:
            if all(s.startswith("meta.") for s in scope.split()):
                return ""
            raise ConvertError(f"{label}: no Notepad++ style for scope {scope!r}")
        return attr("lightStyle", str(ids[0])) + attr("darkStyle", str(ids[1]))

    @staticmethod
    def regex(regex):
        """A tmgrammar.Regex -> its Boost text."""
        check_lookbehinds(regex.tree, regex.label)
        return "(?i)" * regex.icase + tmgrammar.render(regex.tree, BOOST)

    def ref(self, node):
        """An include -> its ref: the repository key, or $self for the top level."""
        key = node.target
        return "$self" if key == SELF else "#" + key

    def write(self, node, depth, out, name=None):
        """Writes a Pattern, and everything inside it, as XML lines into out.
        name is the repository key for a repository entry."""
        pad = "    " * depth
        if node.comment:
            if "--" in node.comment:
                raise ConvertError(f"{node.label}: comments can't contain -- in XML")
            out.append(f"{pad}<!-- {node.comment} -->")
        if node.kind == "include" and name is None:
            out.append(f"{pad}<Include ref=\"{self.ref(node)}\" />")
            return
        if node.content_name:
            raise ConvertError(f"{node.label}: contentName is not supported")
        tag = "<Rule" + (attr("name", name) if name else "")
        if node.kind == "match":
            tag += attr("match", self.regex(node.match))
        elif node.kind == "region":
            tag += attr("begin", self.regex(node.begin)) + attr("end", self.regex(node.end))
        tag += self.styles(node.name, node.label)
        inner = []
        call = bool(node.name and tmgrammar.scope_lookup({"meta.function-call": True}, node.name))
        for key, element in (("captures", "Capture"), ("beginCaptures", "BeginCapture"), ("endCaptures", "EndCapture")):
            for index, cap in sorted(node.raw.get(key, {}).items(), key=lambda kv: int(kv[0])):
                style = self.styles(cap.get("name"), f"{node.label} {key} {index}", call)
                if style:
                    inner.append(f"{pad}    <{element}{attr('index', index)}{style} />")
        if node.kind == "include":
            inner.append(f"{pad}    <Include ref=\"{self.ref(node)}\" />")
        for p in node.patterns:
            self.write(p, depth + 1, inner)
        if inner:
            out += [pad + tag + ">"] + inner + [pad + "</Rule>"]
        else:
            out.append(pad + tag + " />")

    def convert(self):
        version = self.grammar.raw.get("version")
        out = ["    <RAScript" + (attr("version", version) if version else "") + ">"]
        for p in self.grammar.patterns.patterns:
            self.write(p, 2, out)
        out.append("        <Repository>")
        for key, entry in self.grammar.repository.items():
            self.write(entry, 3, out, key)
        out += ["        </Repository>", "    </RAScript>"]
        return "\n".join(out) + "\n"


def main():
    tmgrammar.main("Convert a TextMate grammar into a Notepad++ RAScript.xml, written to stdout.",
                   lambda grammar: Converter(grammar).convert())


if __name__ == "__main__":
    main()
