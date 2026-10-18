#!/bin/bash
make generate
set -euo pipefail

# Test Vim loading
echo "checking gen/rascript.vim"
vim -N -u NONE -i NONE -es \
    -c "try | source gen/rascript.vim | catch | call writefile([v:exception], '/dev/stderr', 'a') | cquit | endtry" \
    -c "if get(b:, 'current_syntax', '') !=# 'rascript' | call writefile(['b:current_syntax was not set'], '/dev/stderr', 'a') | cquit | endif" \
    -c "qall!"
