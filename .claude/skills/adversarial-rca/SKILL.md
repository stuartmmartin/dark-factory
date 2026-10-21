---
name: adversarial-rca
description: Root-cause analysis for bugs, failing tests you do not understand, production errors, incidents — a falsification loop (observe → hypothesize → try to kill → prove with a failing test). Use before proposing any fix whose cause is not proven.
---
# Adversarial RCA

Nothing counts as "the root cause" until a **failing test reproduces it**. Everything short of
that is "likely".

## Loop (maximum 15 rounds)
1. **Observe.** Dispatch two observers in parallel (`roles/observer.md`): one on telemetry and
   logs, one on code and git history. They return facts only.
2. **Hypothesize** (`roles/hypothesizer.md`): at most 3 ranked hypotheses, each with a
   falsifiable prediction. Never re-propose one that was already killed.
3. **Skeptic** (`roles/skeptic.md`): one per hypothesis, trying to kill it. Use your most capable
   model for rank 1.
4. **Correlator** (`roles/correlator.md`): only when 2+ hypotheses survive. Looks for conjunctions.
5. **Prover** (`roles/prover.md`): writes a test that fails on the current code for the surviving
   hypothesis. If it doesn't fail, the hypothesis is not proved; go back to step 2.
6. **Synthesize** (`roles/synthesizer.md`): write the report.

Stop when one hypothesis is proved, when two rounds pass without new evidence (escalate to a
human with the evidence registry), or at 15 rounds.

## Artifacts
`.work/<slug>/investigation/` (gitignored; the failing test is what gets committed, the rest goes through `harvest`):
- `evidence-registry.md`: `E-001 …`, append-only.
- `decision-tree.md`: `H-001 …`, each with status proved, killed or open.
- `rca-report.md`.

The proving test stays in the tree as a regression test (T7).

All role outputs are terse and dense. Keep every piece of technical substance; drop the prose.
