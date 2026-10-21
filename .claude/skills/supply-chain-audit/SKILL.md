---
name: supply-chain-audit
description: Dependency and supply-chain audit — use on any change to pyproject.toml, uv.lock, Dockerfiles, GitHub Actions, or when a CVE is reported. Deterministic checks first, judgment second.
---
# Supply-chain audit
1. `uv export --frozen --no-hashes | uvx pip-audit -r /dev/stdin`: report any vulnerability with
   its fixed version.
2. **New dependency?** Name its maintainer and activity, its license, its transitive footprint
   (`uv tree --package <name>`), and why the standard library or an existing dependency won't do (C13).
3. **Pins:** `uv.lock` is committed and CI uses `--locked`. Nothing is installed from a URL or VCS
   without an ADR.
4. **GitHub Actions:** every `uses:` is pinned to a 40-hex SHA with a version comment.
5. **Dockerfiles:** base images are pinned by digest in prod stages; nothing runs as root; no
   `curl | sh`.
6. **Index confusion:** no extra indexes that could shadow internal `sb-*` names.

Verdict: PASS or FAIL, with evidence for each item.
