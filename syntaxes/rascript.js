/*
Language: RAScript
Author: Joshua Raphael
Description: Syntax grammar for RAScript, a RetroAchievements.org DSL
Category: syntax
Version: _GRAMMAR_VERSION_
*/

function ImportantWordRegex() {
    let words = [
        "byte",
        "word",
        "tbyte",
        "dword",
        "bit0",
        "bit1",
        "bit2",
        "bit3",
        "bit4",
        "bit5",
        "bit6",
        "bit7",
        "bit",
        "low4",
        "high4",
        "bitcount",
        "word_be",
        "tbyte_be",
        "dword_be",
        "float",
        "float_be",
        "mbf32",
        "mbf32_le",
        "double32",
        "double32_be",
        "prev",
        "prior",
        "bcd",
        "identity_transform",
        "ascii_string_equals",
        "unicode_string_equals",
        "remembered",
        "repeated",
        "once",
        "tally",
        "deduct",
        "never",
        "unless",
        "measured",
        "trigger_when",
        "disable_when",
        "always_true",
        "always_false",
        "format",
        "substring",
        "length",
        "range",
        "array_push",
        "array_pop",
        "array_map",
        "array_contains",
        "array_reduce",
        "array_filter",
        "field_map",
        "dictionary_contains_key",
        "any_of",
        "all_of",
        "none_of",
        "sum_of",
        "tally_of",
        "max_of",
        "assert",
        "achievement",
        "achievement_set",
        "rich_presence_display",
        "rich_presence_value",
        "rich_presence_lookup",
        "rich_presence_ascii_string_lookup",
        "rich_presence_macro",
        "rich_presence_conditional_display",
        "leaderboard",
        "__ornext",
    ]
    return "\\b(" + words.join("|") + ")\\b";
}

export default function(hljs) {
    // A TextMate capture is a part of a multi-part match here, with its own scope
    const HEADER = [
        {
            scope: { 1: 'comment', 2: 'keyword', 3: 'comment', 4: 'number' },
            match: [/^\/\/[\t ]*/, /#ID/, /[\t ]*=[\t ]*/, /\d+$/],
            relevance: 0
        },
        // only the RATools release versions listed in https://github.com/Jamiras/RATools/blob/master/Source/Data/Version.cs (0.73-0.79, 1.0-1.4, 1.3.1, 1.4.1, 1.4.2), optionally padded with .0 up to the 4 parts RATools parses (1.0.0.0 is 1.0).
        {
            scope: { 1: 'comment', 2: 'keyword', 3: 'comment', 4: 'number' },
            match: [/^\/\/[\t ]*/, /#MinimumVersion/, /[\t ]*=[\t ]*/, /(?:(?:0\.7[3-9]|1\.[0-4])(?:\.0){0,2}|(?:1\.3\.1|1\.4\.[12])(?:\.0)?)$/],
            relevance: 0
        }
    ];
    const COMMENTS = [
        {
            scope: 'comment',
            begin: /\/\*/,
            end: /\*\//,
            relevance: 0
        },
        {
            scope: 'comment',
            begin: /\/\//,
            end: /$/,
            relevance: 0
        }
    ];

    // the top-level modes, like the TextMate grammar's statements, so a mode can
    // include them the way a TextMate rule includes $self
    const STATEMENTS = [
        // header before comments, since both start with //
        ...HEADER,
        ...COMMENTS,
        // This block helps highlight.js auto detect RAScript syntax
        {
            begin: [
                new RegExp(ImportantWordRegex()),
                /\(/
            ],
            beginScope: {
                1: "title.function.invoke"
            },
            relevance: 10
        },
        hljs.QUOTE_STRING_MODE,
        hljs.C_NUMBER_MODE,
        {
            scope: 'variable.language',
            begin: /\b(this)\b/,
            relevance: 0
        },
        {
            scope: 'keyword',
            begin: /\b(else|for|if|in|return)\b/,
            relevance: 0
        },
        {
            scope: 'literal',
            begin: /\b(true|false)\b/,
            relevance: 0
        },
        {
            scope: 'operator',
            begin: /(\|\||&&|==|!=|>=|<=|=>)/,
            relevance: 0
        },
        {
            scope: 'operator',
            match: /[\+\-\*\/%\^&\^~><!\|]/,
            relevance: 0
        },      
        {
            begin: [
                /\b(function)\b/,
                /[\t ]+/,
                /[a-zA-Z_][\w]*/,
                /\(/
            ],
            beginScope: {
                1: "keyword",
                3: "title.function"
            },
            relevance: 0
        },
        {
            begin: [
                /\b(class)\b/,
                /[\t ]+/,
                /[a-zA-Z_][\w]*/
            ],
            beginScope: {
                1: "keyword",
                3: "title.class"
            },
            relevance: 0
        },
        {
            begin: [
                /[a-zA-Z_][\w]*/,
                /\(/
            ],
            beginScope: {
                1: "title.function.invoke"
            },
            relevance: 0
        },
        {
            scope: 'variable',
            begin: /[a-zA-Z_][\w]*/,
            relevance: 0
        }
    ];
    return {
        case_insensitive: false,
        unicodeRegex: true,
        contains: STATEMENTS
    }
}