#!/bin/bash

export VERSION="$(git describe --always --dirty)"

if [[ ${GITHUB_REF_NAME} != "" ]]; then
    VERSION="$GITHUB_REF_NAME"
fi

sed "s/_GRAMMAR_VERSION_/$VERSION/g" syntaxes/rascript.tmLanguage.json > gen/rascript.tmLanguage.json
plistutil -f xml -i gen/rascript.tmLanguage.json -o gen/rascript.tmLanguage
python3 scripts/tmlanguage2vim.py gen/rascript.tmLanguage.json > gen/rascript.vim
sed "s/_GRAMMAR_VERSION_/$VERSION/g" syntaxes/RAScript.xml > gen/RAScript.xml
sed "s/_GRAMMAR_VERSION_/$VERSION/g" syntaxes/rascript.js > gen/rascript.js