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
    // the top-level modes, like the TextMate grammar's statements, so a mode can
    // include them the way a TextMate rule includes $self. Filled in at the end,
    // once every mode is defined
    const STATEMENTS = [];

    // The modes below mirror the TextMate grammar's rules. Their regexes are the
    // TextMate ones in JavaScript form: \w is [\p{L}\p{M}\p{N}\p{Pc}] and \b a
    // lookaround on it (JavaScript's are ASCII only), and \h is [0-9a-fA-F].
    // highlight.js compiles them with the m and u flags (unicodeRegex). A TextMate
    // capture is a part of a multi-part match here, with its own scope
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
    const STRINGS = [
        {
            scope: 'string',
            begin: /"/,
            end: /"/,
            contains: [
                // unicode escape: \u and exactly four hex digits, one character (\u00e9 is é)
                {
                    scope: 'char.escape',
                    match: /\\u[0-9a-fA-F]{4}/,
                    relevance: 0
                },
                // any other escape: RATools reads \t \n \r, and drops the backslash before any other character
                {
                    scope: 'char.escape',
                    match: /\\./,
                    relevance: 0
                },
                {
                    scope: { 1: 'template-variable', 2: 'variable', 3: 'template-variable' },
                    match: [/\{/, /[0-9]+/, /\}/],
                    relevance: 0
                }
            ],
            relevance: 0
        }
    ];
    const CONTROLS = [
        // if with its condition in parentheses: the condition is its own region so if (x) { isn't read as the lambda (x) { ... }
        {
            begin: [/(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))if/, /[\t ]*\(/],
            beginScope: { 1: 'keyword' },
            end: /\)/,
            contains: STATEMENTS,
            relevance: 0
        },
        // for loop header: in is only a keyword after for and the loop variable, elsewhere it is a normal name (in = 1, function in(...))
        {
            scope: { 1: 'keyword', 3: 'variable', 5: 'keyword' },
            match: [/(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))for/, /[\t ]+/, /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))(?!\d)[\p{L}\p{M}\p{N}\p{Pc}]+/, /[\t ]+/, /in(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/],
            relevance: 0
        },
        {
            scope: 'keyword',
            match: /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))(if|else|for|return)(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/,
            relevance: 0
        }
    ];
    // a function definition from the function keyword to the ) closing its parameter list, so parameters can span lines. The keyword, name and ( must be on the same line
    const FUNCTION_DEFINITIONS = [
        {
            begin: [/(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))function(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/, /[^\S\r\n]*/, /[\p{L}\p{M}\p{N}\p{Pc}]+/, /[^\S\r\n]*\(/],
            beginScope: { 1: 'keyword', 3: 'title.function' },
            end: /\)/,
            contains: [
                ...COMMENTS,
                // default value: everything after = up to the next , or ) is highlighted as usual. Parentheses, blocks and brackets in the value consume their own , and )
                {
                    begin: /=(?!=)/,
                    end: /(?=[,)])/,
                    contains: STATEMENTS,
                    relevance: 0
                },
                // parameter name
                {
                    scope: 'params',
                    match: /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))(?!\d)[\p{L}\p{M}\p{N}\p{Pc}]+/,
                    relevance: 0
                }
            ],
            relevance: 0
        }
    ];
    const BOOLEANS = [
        {
            scope: 'literal',
            match: /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))(?:true|false)(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/,
            relevance: 0
        }
    ];
    const NUMBERS = [
        // whole numbers and decimals like 19.25, scoped as one number including the dot
        {
            scope: 'number',
            match: /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))[0-9]+(\.[0-9]+)?(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/,
            relevance: 0
        },
        {
            scope: 'number',
            match: /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))0x[0-9a-fA-F]+(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/,
            relevance: 0
        }
    ];
    const CLASS_DEFINITIONS = [
        {
            scope: { 1: 'keyword', 3: 'title.class' },
            match: [/(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))class(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/, /[\t ]*/, /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))(?!\d)[\p{L}\p{M}\p{N}\p{Pc}]+/],
            relevance: 0
        }
    ];
    const VARIABLE_LANGUAGE_THIS = [
        {
            scope: 'variable.language',
            match: /(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))this(?:(?<=[\p{L}\p{M}\p{N}\p{Pc}])(?![\p{L}\p{M}\p{N}\p{Pc}])|(?<![\p{L}\p{M}\p{N}\p{Pc}])(?=[\p{L}\p{M}\p{N}\p{Pc}]))/,
            relevance: 0
        }
    ];

    STATEMENTS.push(
        // header before comments, since both start with //
        ...HEADER,
        ...COMMENTS,
        ...CONTROLS,
        ...FUNCTION_DEFINITIONS,
        ...BOOLEANS,
        ...STRINGS,
        ...NUMBERS,
        ...CLASS_DEFINITIONS,
        ...VARIABLE_LANGUAGE_THIS,
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
    );
    return {
        case_insensitive: false,
        unicodeRegex: true,
        contains: STATEMENTS
    }
}