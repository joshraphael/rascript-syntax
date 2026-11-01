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
# Styles: each Notepad++ style is a light and a dark WordsStyle with its own
# ID and color (the plugin picks one of the two for the current theme), and
# each TextMate scope maps to one style by name. The longest scope prefix that
# matches wins (see scope_lookup), e.g. "variable.other.assignment.rascript" ->
# VARIABLE-ASSIGNMENT, not variable.other's VARIABLES.
# --------------------------------------------------------------------------

# (name, light ID, light color, dark ID, dark color), written in this order.
# The light names get LIGHT- in front, the dark ones DARK-. IDs 32-39 are
# reserved by Scintilla (STYLE_DEFAULT, STYLE_LINENUMBER, ...)
STYLES = [
    ("VARIABLES",                    1, "001080",  2, "9CDCFE"),
    ("CONTROL",                      3, "B5200D",  4, "C586C0"),
    ("THIS",                         5, "0F4A85",  6, "569CD6"),
    ("BOOLEANS",                     7, "0F4A85",  8, "569CD6"),
    ("DECIMALS",                     9, "096D48", 10, "B5CEA8"),
    ("HEXADECIMALS",                11, "096D48", 12, "B5CEA8"),
    ("CLASS",                       13, "0F4A85", 14, "569CD6"),
    ("CLASS-NAME",                  15, "185E73", 16, "4EC9B0"),
    ("FUNCTION",                    17, "0F4A85", 18, "569CD6"),
    ("FUNCTION-CALLS",              19, "5E2CBC", 20, "DCDCAA"),
    ("FUNCTION-NAME",               21, "5E2CBC", 22, "DCDCAA"),
    ("STRINGS",                     23, "0F4A85", 24, "CE9178"),
    ("LINE-COMMENTS",               25, "515151", 26, "6A9955"),
    ("BLOCK-COMMENTS",              27, "515151", 28, "6A9955"),
    ("HEADER-ID-KEY",               29, "0F4A85", 30, "569CD6"),
    ("HEADER-ID-VALUE",             40, "096D48", 41, "B5CEA8"),
    ("HEADER-MINIMUMVERSION-KEY",   42, "0F4A85", 43, "569CD6"),
    ("HEADER-MINIMUMVERSION-VALUE", 44, "096D48", 45, "B5CEA8"),
    ("STRING-PLACEHOLDER",          46, "0F4A85", 47, "569CD6"),
    ("STRING-ESCAPE",               48, "EE0000", 49, "D7BA7D"),
    ("VARIABLE-ASSIGNMENT",         50, "001080", 51, "9CDCFE"),
    ("PARAMETERS",                  52, "001080", 53, "9CDCFE"),
    ("BUILTIN-FUNCTIONS",           54, "5E2CBC", 55, "DCDCAA"),
    ("NAMED-ARGUMENTS",             56, "001080", 57, "9CDCFE"),
]
RESERVED = range(32, 40)

SCOPE_STYLES = {
    "variable.other": "VARIABLES",
    "keyword.control": "CONTROL",
    "variable.language.this": "THIS",
    "constant.language.boolean": "BOOLEANS",
    "constant.numeric.decimal": "DECIMALS",
    "constant.numeric.hexadecimal": "HEXADECIMALS",
    "keyword.class": "CLASS",
    "entity.name.class": "CLASS-NAME",
    "keyword.function": "FUNCTION",
    "entity.name.function": "FUNCTION-NAME",
    "string.quoted.double": "STRINGS",
    "comment.line.double-slash": "LINE-COMMENTS", "punctuation.definition.comment.single": "LINE-COMMENTS",
    "comment.block": "BLOCK-COMMENTS", "punctuation.definition.comment.block": "BLOCK-COMMENTS",
    "keyword.other.id": "HEADER-ID-KEY",
    "constant.numeric.id": "HEADER-ID-VALUE",
    "keyword.other.version": "HEADER-MINIMUMVERSION-KEY",
    "constant.numeric.version": "HEADER-MINIMUMVERSION-VALUE",
    "punctuation.definition.template-expression": "STRING-PLACEHOLDER",
    "constant.character.escape": "STRING-ESCAPE",
    "variable.other.assignment": "VARIABLE-ASSIGNMENT",
    "variable.parameter": "PARAMETERS",
    "support.function": "BUILTIN-FUNCTIONS",
    "variable.parameter.function-call": "NAMED-ARGUMENTS",
}

# Used instead of SCOPE_STYLES for the captures of a rule named
# meta.function-call: a function name there is a call, everywhere else a
# definition (FUNCTION-NAME)
CALL_STYLES = {
    "entity.name.function": "FUNCTION-CALLS",
}

# style name -> (light ID, dark ID)
STYLE_IDS = {name: (light, dark) for name, light, _, dark, _ in STYLES}

# The language as the plugin knows it: Notepad++ shows the name in its
# Language menu, and the plugin's lexer and the <RAScript> element it reads
# use the same name
LANGUAGE = "RAScript"
EXTENSION = "rascript"


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
        style = call and tmgrammar.scope_lookup(CALL_STYLES, scope) or tmgrammar.scope_lookup(SCOPE_STYLES, scope)
        if style is None:
            if all(s.startswith("meta.") for s in scope.split()):
                return ""
            raise ConvertError(f"{label}: no Notepad++ style for scope {scope!r}")
        light, dark = STYLE_IDS[style]
        return attr("lightStyle", str(light)) + attr("darkStyle", str(dark))

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

    @staticmethod
    def lexer_styles():
        """The <LexerStyles> lines: a light and a dark WordsStyle per style, a
        blank line between styles."""
        out, past_reserved = [], False
        for name, light, light_color, dark, dark_color in STYLES:
            if light in RESERVED or dark in RESERVED:
                raise ConvertError(f"style {name}: style IDs 32-39 are reserved by Scintilla")
            if out:
                out.append("")
            # the note goes before the first style after the gap
            if light > RESERVED[-1] and not past_reserved:
                out.append("            <!-- styleIDs 32-39 are reserved by Scintilla, do not use -->")
                past_reserved = True
            for mode, i, color in (("LIGHT", light, light_color), ("DARK", dark, dark_color)):
                out.append(f"            <WordsStyle{attr('name', f'{mode}-{name}')}{attr('styleID', str(i))}{attr('fgColor', color)} />")
        return out

    def convert(self):
        out = ['<NotepadPlus version="2">',
               "    <Languages>",
               f'        <Language{attr("name", LANGUAGE)}{attr("ext", EXTENSION)} commentLine="" commentStart="" commentEnd="">',
               "        </Language>",
               "    </Languages>",
               "    <LexerStyles>",
               f'        <LexerType{attr("name", LANGUAGE)}{attr("desc", LANGUAGE + " file")} ext="" excluded="no">']
        out += self.lexer_styles()
        out += ["        </LexerType>", "    </LexerStyles>"]
        version = self.grammar.raw.get("version")
        out.append("    <RAScript" + (attr("version", version) if version else "") + ">")
        for p in self.grammar.patterns.patterns:
            self.write(p, 2, out)
        out.append("        <Repository>")
        for key, entry in self.grammar.repository.items():
            self.write(entry, 3, out, key)
        out += ["        </Repository>", "    </RAScript>", "</NotepadPlus>"]
        return "\n".join(out) + "\n"


def main():
    tmgrammar.main("Convert a TextMate grammar into a Notepad++ RAScript.xml, written to stdout.",
                   lambda grammar: Converter(grammar).convert())


if __name__ == "__main__":
    main()
