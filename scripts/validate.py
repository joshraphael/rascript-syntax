#!/usr/bin/env python3

import argparse
import json
import plistlib
import re
import sys
import xml.etree.ElementTree as ET


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


def check_notepad(xml_path):
    tokens = ET.parse(xml_path).getroot().findall("RAScript/Token")
    if not tokens:
        raise ValueError(f"{xml_path} has no RAScript tokens")
    for token in tokens:
        name, regex = token.get("name"), token.get("regex")
        if token.get("type") == "NORMAL" and regex is None:
            raise ValueError(f"{xml_path}: token {name!r} has no regex")
        try:
            re.compile(regex or "")
        except re.error as e:
            raise ValueError(f"{xml_path}: token {name!r}: {e}") from None


def main():
    parser = argparse.ArgumentParser(description="Check that generated grammar files are well formed.")
    checks = parser.add_subparsers(dest="check", required=True)
    tm = checks.add_parser("tmlanguage", help="TextMate grammar JSON and its Sublime plist")
    tm.add_argument("json", help="rascript.tmLanguage.json")
    tm.add_argument("plist", help="rascript.tmLanguage")
    npp = checks.add_parser("notepad", help="Notepad++ grammar XML")
    npp.add_argument("xml", help="RAScript.xml")
    args = parser.parse_args()
    try:
        if args.check == "tmlanguage":
            check_tmlanguage(args.json, args.plist)
        elif args.check == "notepad":
            check_notepad(args.xml)
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
