# User Prompts

`AskUserQuestion` allows at most 4 options and 4 questions per call. For more, fall back to prose:

- 5+ options → a lettered list (A, B, C…), one per line, each with a one-line description; the letter is the reply token.
- 5+ questions → a numbered list, answered by number.
- Prose prompts don't end the turn on their own — after the list, write "STOP. Wait for the user's reply before continuing," and don't infer the choice. Parse the reply's first letter case-insensitively; if ambiguous, ask once, then halt.
