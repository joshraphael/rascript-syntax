#!/usr/bin/env python3

import datetime
import json
import os
import sys

MAINTAINER = "Joshua Raphael"
URL = "https://github.com/joshraphael/rascript-syntax"
REMARK = "Syntax grammar for RAScript, a RetroAchievements.org DSL"


class ConvertError(Exception):
    pass

class Converter:
    def __init__(self, grammar, source_name):
        self.g, self.source_name = grammar, source_name
        self.lang = grammar.get("scopeName", "source.tmlang").split(".")[-1]

    def convert(self):
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
                "syntax iskeyword @,48-57,_,192-255", "syntax sync fromstart", "",
                f"let b:current_syntax = '{self.lang}'", "",
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
