---
description: Run the code-review gate on this branch (optionally a focus - all|security|architecture|engineering)
---
Compute `BASE=$(git merge-base HEAD origin/main 2>/dev/null || git merge-base HEAD main)`. If
`git diff $BASE` is empty, say "Nothing to review" and stop. Otherwise run the `code-review` skill
with base `$BASE` and focus `$ARGUMENTS` (default `all`), and report the verdict.
