## What and why

<!-- One paragraph. Link the spec/plan or ADR. -->

## Business rules touched

<!-- List use cases / policies and the R<n> rules added or changed. "None" if infrastructure only. -->

## Test evidence

<!-- Paste the RED failure and the GREEN run for new behaviour (or link the CI run). -->

## Knowledge harvested

<!-- Larger changes: the table from the harvest skill (each ruling, trap or deferred item → test,
comment, CLAUDE.md, CONTEXT.md, ADR or ticket, or "dropped: why"). Otherwise "none (no working docs)". -->

## Checklist

- [ ] `make check` passes locally
- [ ] New/changed business rules have `test_R<n>_*` tests
- [ ] Working docs harvested (`harvest` skill); none committed under `docs/`
- [ ] `make graph` run and `docs/generated/` committed (if members/APIs changed)
- [ ] No edits to human-owned guardrail files, or an owner is requested for review
- [ ] Opened as **draft** if AI-authored
