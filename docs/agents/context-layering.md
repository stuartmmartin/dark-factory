# Context layering

Agents pay for every token they read, and irrelevant context makes them worse. The layers go from
cheapest to most expensive:

1. **`AGENTS.md`** (always loaded, ≤ 100 lines, enforced): the commands, the invariants, where
   code goes, and the definition of done. `CLAUDE.md` imports it and adds Claude-specific notes.
2. **`.claude/rules/*.md`** (loaded only when matching paths are touched): short, layer-specific
   reminders that cite rule IDs.
3. **Per-service `CLAUDE.md` and `CONTEXT.md`**: gotchas, and the domain glossary (Definition /
   *Avoid* / *Invariant*).
4. **Skills** (only the name and description load until invoked): procedures such as TDD, review,
   spec and RCA.
5. **`docs/generated/module-index.md`**, plus `make blast-radius` / `make deps`: navigate without
   opening files. Generated from code, so it's never stale (CI drift check).
6. **Source files**: read last, and only what the task needs.

`docs/conventions/*.md` is the single source of rules. Everything else cites IDs such as `A3` and
never copies the rule text, so rules can't drift apart. `.claude/settings.json` denies reads of
generated JSON, lockfiles, virtualenvs and secrets, so they can't flood context.

We deliberately don't run embeddings/RAG or a code knowledge graph (ADR-0006). The LSP plugin,
the build graph and grep are deterministic and never stale. Revisit at around 500k LOC or when the
first Go service arrives.
