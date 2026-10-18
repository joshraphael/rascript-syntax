#!/usr/bin/env python3

import argparse
import json
import plistlib
import sys


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


def main():
    parser = argparse.ArgumentParser(description="Check that generated grammar files are well formed.")
    checks = parser.add_subparsers(dest="check", required=True)
    tm = checks.add_parser("tmlanguage", help="TextMate grammar JSON and its Sublime plist")
    tm.add_argument("json", help="rascript.tmLanguage.json")
    tm.add_argument("plist", help="rascript.tmLanguage")
    args = parser.parse_args()
    try:
        if args.check == "tmlanguage":
            check_tmlanguage(args.json, args.plist)
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
