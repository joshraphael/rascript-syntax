#!/usr/bin/env node

import fs from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

function fail(message) {
    console.error(message);
    process.exit(1);
}

// Every match/begin/end/while regex in a TextMate grammar, with where it is,
// e.g. ["repository.strings.patterns[0].begin", "\""]
function grammarRegexes(node, path, out) {
    if (Array.isArray(node)) {
        node.forEach((child, i) => grammarRegexes(child, `${path}[${i}]`, out));
    } else if (node && typeof node === "object") {
        for (const [key, value] of Object.entries(node)) {
            if (["match", "begin", "end", "while"].includes(key) && typeof value === "string") {
                out.push([`${path}.${key}`, key, value]);
            } else {
                grammarRegexes(value, `${path}.${key}`, out);
            }
        }
    }
    return out;
}

async function checkTmlanguage(jsonPath) {
    const onig = require("vscode-oniguruma");
    await onig.loadWASM(fs.readFileSync(require.resolve("vscode-oniguruma/release/onig.wasm")).buffer);
    const grammar = JSON.parse(fs.readFileSync(jsonPath, "utf8"));
    for (const [path, key, regex] of grammarRegexes(grammar, "grammar", [])) {
        // end and while can refer back to begin's groups (\1); those are filled
        // in at runtime, so stand in a literal for them here
        const pattern = key === "end" || key === "while" ? regex.replace(/(?<!\\)((?:\\\\)*)\\[1-9]/g, "$1x") : regex;
        try {
            new onig.OnigScanner([pattern]).dispose();
        } catch (e) {
            fail(`${jsonPath}: ${path}: ${e.message}: ${regex}`);
        }
    }
}

async function checkHighlightjs(jsPath) {
    // a data: URL always loads as an ES module, whatever folder the file is in
    const source = fs.readFileSync(jsPath, "utf8");
    let language;
    try {
        language = (await import("data:text/javascript;base64," + Buffer.from(source).toString("base64"))).default;
    } catch (e) {
        fail(`${jsPath}: ${e.name}: ${e.message}`);
    }
    if (typeof language !== "function") {
        fail(`${jsPath}: doesn't export a highlight.js language function`);
    }
    // debugMode makes highlight.js throw on grammar errors instead of falling
    // back to plain text; the first highlight compiles every mode's regex
    const hljs = require("highlight.js/lib/core");
    hljs.debugMode();
    hljs.registerLanguage("rascript", language);
    try {
        hljs.highlight("", { language: "rascript" });
    } catch (e) {
        fail(`${jsPath}: ${e.message}`);
    }
}

const [check, ...files] = process.argv.slice(2);
try {
    if (check === "tmlanguage" && files.length === 1) {
        await checkTmlanguage(files[0]);
    } else if (check === "highlightjs" && files.length === 1) {
        await checkHighlightjs(files[0]);
    } else {
        fail("usage: validate.mjs tmlanguage rascript.tmLanguage.json | highlightjs rascript.js");
    }
} catch (e) {
    fail(`${e.name}: ${e.message}`);
}
