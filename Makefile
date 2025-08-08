deps:
	sudo apt update
	sudo apt install libplist-utils

clean:
	rm -f rascript.tmLanguage
	rm -f RAScript.sublime-package
	rm -f ~/.config/sublime-text/Packages/User/rascript.tmLanguage

generate: clean
	plistutil -f xml -i rascript.tmLanguage.json -o rascript.tmLanguage

sublime: generate
	zip -r RAScript.sublime-package rascript.tmLanguage
	cp rascript.tmLanguage ~/.config/sublime-text/Packages/User