#!/bin/bash
make generate
set -euo pipefail

# Test Vim loading
echo "checking gen/rascript.vim"
vim -N -u NONE -i NONE -es \
    -c "try | source gen/rascript.vim | catch | call writefile([v:exception], '/dev/stderr', 'a') | cquit | endtry" \
    -c "if get(b:, 'current_syntax', '') !=# 'rascript' | call writefile(['b:current_syntax was not set'], '/dev/stderr', 'a') | cquit | endif" \
    -c "qall!"

# Test the TextMate grammar JSON and Sublime plist parse and match
echo "checking gen/rascript.tmLanguage.json and gen/rascript.tmLanguage"
python3 scripts/validate.py tmlanguage gen/rascript.tmLanguage.json gen/rascript.tmLanguage

# Test the Notepad++ XML parses and its token regexes compile
echo "checking gen/RAScript.xml"
python3 scripts/validate.py notepad gen/RAScript.xml

# Test the TextMate grammar regexes compile in Oniguruma, the regex engine VS Code uses
echo "checking gen/rascript.tmLanguage.json regexes"
npm ci --silent --prefix scripts
node scripts/validate.mjs tmlanguage gen/rascript.tmLanguage.json
