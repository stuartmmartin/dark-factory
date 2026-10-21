---
name: tighten
description: Simplify a finished branch before review — make code less verbose and docs less wordy without changing behaviour or losing readability. Use once per branch, when it is ready to go into main, after the tests pass and before /review. Not per commit or per task.
---
# Tighten

A cleanup pass over the whole diff, run by the implementer once the tests are green and before
`/review`. It edits the diff, and the review gate judges the result. Behaviour stays the same. If a shorter version is harder
to read, keep the longer one.

## Scope
`git diff $BASE` plus untracked files you added. Leave untouched code alone, even when it could be
shorter: note it as a follow-up instead.

## Code
- Remove duplication: two near-identical blocks become one function, or one loop.
- Inline wrappers that only forward a call, and variables used once that add no meaning.
- Flatten nesting with early returns and guard clauses.
- Prefer clear built-ins and comprehensions to hand-written loops, when the result reads at a glance.
- Reuse an existing `sb_*` helper or port method before keeping a new one.
- Delete dead code, unused parameters, and comments that restate the code. Keep comments that say
  why.

Never trade away a rule to save lines: keep the use case shape (A4), type hints (C1), pure
policies (A5), thin interface code (A8), explicit Decimal rounding (C3), and one responsibility per
file (C11). Never change what an `R<n>` rule means, and never delete or weaken a test.

## Docs
Covers Markdown, docstrings, comments, `CLAUDE.md`, `CONTEXT.md`, ADRs and skills.
- One fact in one place, with links to it from anywhere else that needs it.
- Short sentences with plain verbs. Cut filler, hedges and throat-clearing openers.
- Cut words that carry nothing: "delve", "leverage", "foster", "genuinely", "it's worth noting",
  "importantly". No summary closers ("In short", "Bottom line"), no rhetorical "Question? Answer."
  and no "This isn't X, it's Y" or "X, not Y" framing. State the point directly.
- Prefer a table or a list to a paragraph that enumerates.
- Keep rule IDs, file paths, commands and numbers exact. `agent-lint` size limits still apply.

## Steps
1. Read the diff once, end to end. List candidate edits.
2. Make the edits. Run `make check-fast` (and `make test PKG=…` for the members you touched). Every
   test that passed before must still pass, unchanged.
3. Report, so the reviewer can see what moved:
   ```
   Tightened: <files>, <lines before> → <lines after>
   Kept as is: <path:line> — <why the longer form reads better>
   Follow-ups: <verbose code outside the diff, if any>
   ```
