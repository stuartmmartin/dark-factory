# AI-agent scaffolding

How dark_factory lets agents write most of the code while humans stay in control of business logic.

| Doc | What |
|---|---|
| [context-layering.md](context-layering.md) | What an agent reads, in what order, and why (token budget) |
| [hooks.md](hooks.md) | The guards that run on every tool call and when an agent stops |
| [skills.md](skills.md) | Skills, agents and commands, and when each is used |
| [review-gates.md](review-gates.md) | Local `/review` and the CI AI review, with verdicts and overrides |
| [dark-factory-runbook.md](dark-factory-runbook.md) | Running long autonomous work safely |

Everything executable lives in `tools/agentkit` (`sb-agentkit`) and is tested. `make agent-lint`
keeps the Markdown layer coherent: rule IDs, links and frontmatter.
