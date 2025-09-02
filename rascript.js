/*
Language: RAScript
Author: Joshua Raphael
Description: Syntax grammar for RAScript, a RetroAchievements.org DSL
Category: syntax
Version: <GRAMMAR_VERSION>
*/
export default function(hljs) {
    return {
        case_insensitive: false,
        contains: [
            hljs.C_LINE_COMMENT_MODE,
            hljs.QUOTE_STRING_MODE,
            hljs.C_NUMBER_MODE,
            hljs.COMMENT(
                '/\\*',
                '\\*/',
            ),
            {
                className: 'variable.language',
                begin: /\b(this)\b/
            },
            {
                className: 'keyword',
                begin: /\b(function|class|else|for|if|in|return)\b/
            },
            {
                className: 'literal',
                begin: /\b(true|false)\b/
            },
            {
                className: 'operator',
                begin: /(\|\||\&\&|\=\=|\!\=|\>\=|\<\=|\=\>)/
            },
            {
                scope: 'operator',
                match: /[\+\-\*\/\%\^\&\^\~\>\<\!\|]/,
                relevance: 0
            },      
            {
                begin: [
                    /function[\t ]+/,
                    /[a-zA-Z_][\w]*/,
                    /\(/
                ],
                beginScope: {
                    2: "title.function"
                }
            },
            {
                begin: [
                    /class[\t ]+/,
                    /[a-zA-Z_][\w]*/
                ],
                beginScope: {
                    2: "title.class"
                }
            },
            {
                begin: [
                    /[a-zA-Z_][\w]*/,
                    /\(/
                ],
                beginScope: {
                    1: "title.function.invoke"
                }
            },
            {
                className: 'variable',
                begin: /[a-zA-Z_][\w]*/,
                relevance: 0
            }
        ]
    }
}