#!/usr/bin/env python3

import argparse
import json
import plistlib
import re
import sys
import xml.etree.ElementTree as ET

import tmgrammar


def first_difference(a, b, path="grammar"):
    if type(a) is not type(b):
        return path
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return f"{path}.{key}"
            diff = first_difference(a[key], b[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return path
        for i, (x, y) in enumerate(zip(a, b)):
            diff = first_difference(x, y, f"{path}[{i}]")
            if diff:
                return diff
        return None
    return None if a == b else path


def check_tmlanguage(json_path, plist_path):
    with open(json_path, encoding="utf-8") as f:
        grammar = json.load(f)
    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)
    diff = first_difference(grammar, plist)
    if diff:
        raise ValueError(f"{plist_path} doesn't match {json_path} at {diff}")


def grammar_regexes(node, path="grammar"):
    """Every match/begin/end/while regex in a TextMate grammar, with where it is."""
    if isinstance(node, list):
        for i, child in enumerate(node):
            yield from grammar_regexes(child, f"{path}[{i}]")
    elif isinstance(node, dict):
        for key, value in node.items():
            if key in ("match", "begin", "end", "while") and isinstance(value, str):
                yield f"{path}.{key}", value
            else:
                yield from grammar_regexes(value, f"{path}.{key}")


def check_regexes(json_path):
    with open(json_path, encoding="utf-8") as f:
        grammar = json.load(f)
    for path, regex in grammar_regexes(grammar):
        try:
            tree, icase, _ = tmgrammar.parse(regex)
        except tmgrammar.ConvertError as e:
            raise ValueError(f"{json_path}: {path}: {e} in {regex!r}") from None
        back = "(?i)" * icase + tmgrammar.render(tree, tmgrammar.ONIGURUMA)
        if back != regex:
            raise ValueError(f"{json_path}: {path}: {regex!r} comes back from the regex tree as {back!r}")


def check_notepad(xml_path):
    root = ET.parse(xml_path).getroot()
    grammar = root.find("RAScript")
    if grammar is None:
        raise ValueError(f"{xml_path} has no RAScript element")
    styles = {int(s.get("styleID")) for s in root.iter("WordsStyle")}
    repository = grammar.find("Repository")
    names = {r.get("name") for r in repository.findall("Rule")} if repository is not None else set()
    rules = list(grammar.iter("Rule"))
    if not rules:
        raise ValueError(f"{xml_path} has no RAScript rules")
    for rule in rules:
        where = f"rule {rule.get('name') or rule.get('match') or rule.get('begin')!r}"
        kinds = [a for a in ("match", "begin", "end") if rule.get(a) is not None]
        if kinds not in ([], ["match"], ["begin", "end"]):
            raise ValueError(f"{xml_path}: {where} needs match, begin and end, or neither, not {kinds}")
        for attr in kinds:
            try:
                re.compile(rule.get(attr))
            except re.error as e:
                raise ValueError(f"{xml_path}: {where} {attr}: {e}") from None
        for e in [rule] + rule.findall("Capture") + rule.findall("BeginCapture") + rule.findall("EndCapture"):
            for mode in ("lightStyle", "darkStyle"):
                if e.get(mode) is not None and int(e.get(mode)) not in styles:
                    raise ValueError(f"{xml_path}: {where} {mode} {e.get(mode)} has no WordsStyle")
    for include in grammar.iter("Include"):
        ref = include.get("ref")
        if ref != "$self" and (not ref.startswith("#") or ref[1:] not in names):
            raise ValueError(f"{xml_path}: include {ref!r} names no repository rule")


def main():
    parser = argparse.ArgumentParser(description="Check that generated grammar files are well formed.")
    checks = parser.add_subparsers(dest="check", required=True)
    tm = checks.add_parser("tmlanguage", help="TextMate grammar JSON and its Sublime plist")
    tm.add_argument("json", help="rascript.tmLanguage.json")
    tm.add_argument("plist", help="rascript.tmLanguage")
    rx = checks.add_parser("regexes", help="TextMate grammar regexes round-trip through tmgrammar.py's regex tree")
    rx.add_argument("json", help="rascript.tmLanguage.json")
    npp = checks.add_parser("notepad", help="Notepad++ grammar XML")
    npp.add_argument("xml", help="RAScript.xml")
    args = parser.parse_args()
    try:
        if args.check == "tmlanguage":
            check_tmlanguage(args.json, args.plist)
        elif args.check == "regexes":
            check_regexes(args.json)
        elif args.check == "notepad":
            check_notepad(args.xml)
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
