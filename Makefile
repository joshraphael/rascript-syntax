SHELL := /bin/bash

deps:
	sudo apt update
	sudo apt install libplist-utils

clean:
	rm -rf gen/
	mkdir -p gen/
	rm -f ~/.config/sublime-text/Packages/User/rascript.tmLanguage

generate: clean
	./scripts/generate.sh

sublime: generate
	cd gen && zip -r RAScript.sublime-package rascript.tmLanguage
	cp gen/rascript.tmLanguage ~/.config/sublime-text/Packages/User

vim: generate
	mkdir -p ~/.vim/syntax ~/.vim/ftdetect
	cp gen/rascript.vim ~/.vim/syntax/rascript.vim
	echo 'autocmd BufRead,BufNewFile *.rascript setfiletype rascript' > ~/.vim/ftdetect/rascript.vim