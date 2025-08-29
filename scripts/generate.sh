#!/bin/bash

export VERSION="$(git describe --always --dirty)"

if [[ ${GITHUB_REF_NAME} != "" ]]; then
    VERSION="$GITHUB_REF_NAME"
fi

sed "s/<GRAMMAR_VERSION>/$VERSION/g" rascript.tmLanguage.json > gen/rascript.tmLanguage.json
plistutil -f xml -i gen/rascript.tmLanguage.json -o gen/rascript.tmLanguage
sed "s/<GRAMMAR_VERSION>/$VERSION/g" RAScript.xml > gen/RAScript.xml