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
