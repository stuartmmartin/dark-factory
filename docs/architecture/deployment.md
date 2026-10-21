# Deployment

How a service gets from `main` to a cluster: images, Kustomize manifests, the gated deploy
workflow, secrets, and rollback. Nothing here runs locally; local development is
[`environment_setup.md`](../environment_setup.md). Decision: [ADR 0013](../adr/0013-kustomize-no-argo.md)
(Kustomize, no Argo).

## Images

Each service has one Dockerfile (`services/<svc>/Dockerfile`, built from the repository root) with
these stages:

| Stage | Holds | Used by |
|---|---|---|
| `base` | Pinned Python and `uv` (both by digest) | every stage |
| `deps` | Third-party dependencies only; changes only with `uv.lock` or a manifest | cache layer |
| `dev` | `deps` plus dev dependencies, **no source**: compose bind-mounts `src`, `migrations` and `libs/py` | `make up ledger` |
| `prod` | Source copied and installed non-editable, no dev dependencies, runs as user `10001` (non-root) | `images.yml`, Kubernetes |

The prod image's entrypoint is `python -m`, so one image runs all four processes:
`ledger.main` (default), `ledger.worker`, `ledger.consumer` and `ledger.migrate`. Each Deployment
and the migrate Job pass the module as `args`.

`images.yml` builds the `prod` target for every affected service **only on `main`** (a push, or
a manual run dispatched from `main`; every job requires `refs/heads/main`), from the member's
own directory (`services/<name>/Dockerfile`, build-arg `SERVICE=<package>`). It pushes
`ghcr.io/<owner>/dark-factory-<kebab>:<sha>` (plus a moving `:latest-dev` on push) and attests the
build provenance (SLSA, signed with the workflow's identity). Naming: the Python package, the
service directory and the compose names keep `_` (`demo_svc`); the image, `deploy/k8s/<kebab>/`
and every Kubernetes resource name use the hyphenated form (`demo-svc`).

## Kustomize layout

```
deploy/k8s/
  base/                     default-deny NetworkPolicy shared by every service
  cluster-admin/            Namespaces with Pod Security labels (applied by a cluster admin only)
  ledger/
    base/                   Deployments (api, worker, consumer), migrate Job, Service, ConfigMap,
                            NetworkPolicies; references the image, secrets and env by name
    overlays/dev/           namespace dark-factory-dev, 1 replica each, dev auth and admin
    overlays/prod/          namespace dark-factory-prod, replicas and resources, oidc auth
```

Render an overlay with `make k8s-render SVC=ledger ENV=dev`. `make k8s-validate` renders every
overlay plus `cluster-admin` and checks them with `kubeconform`; CI runs it as the `k8s` job.
Pods run non-root with a read-only root filesystem, no privilege escalation, all capabilities
dropped and the `RuntimeDefault` seccomp profile, so they pass the Pod Security `restricted`
level that the namespaces enforce. The default-deny NetworkPolicy blocks all traffic; the ledger
base allows DNS, API ingress and the egress it needs. The prod egress CIDRs are TEST-NET
placeholders until a human replaces them with the managed Postgres, Kafka and Temporal ranges.

The Namespaces are **not** part of the overlays. A cluster admin applies them once per cluster
(`kubectl apply -k deploy/k8s/cluster-admin`), so the deploy credential never needs permission to
create a Namespace.

## The deploy workflow

`deploy.yml` is a manual `workflow_dispatch` with three inputs: `service`, `environment`
(`dev` or `prod`) and `sha`. Its gates, in order:

1. **Builds and deploys only from `main`.** The run must be dispatched from `refs/heads/main`,
   and the SHA must be an ancestor of `origin/main` (`git merge-base --is-ancestor`). The inputs
   are validated (service name, environment, a full 40-character SHA) and reach the shell only
   through environment variables. The service may be given as `demo_svc` or `demo-svc`; the
   workflow deploys the hyphenated form (`deploy/k8s/demo-svc/`, image `dark-factory-demo-svc`,
   Job `demo-svc-migrate`), because Kubernetes names are DNS labels.
2. **The Environment gates the job.** GitHub Environments `dev` and `prod` both restrict
   deployment branches to `main`, and `prod` also requires reviewers, so a prod run waits for a
   human approval.
3. **Deploy by digest.** The `<sha>` tag is resolved once to an image digest, and every workload
   runs `image@sha256:...`: after `kustomize edit set image`, the rendered manifests are checked
   and every `image:` field must equal exactly that `image@digest`, or the deploy stops.
4. **Provenance is verified before any kubeconfig is written.** `gh attestation verify` proves the
   digest was built by `images.yml` in this repository, from `refs/heads/main`, at exactly that
   SHA, so a re-pointed tag is refused. The signer is pinned with `--cert-identity`
   (`https://github.com/<repo>/.github/workflows/images.yml@refs/heads/main`), and
   `--deny-self-hosted-runners` refuses attestations made on self-hosted runners. Attestations require a public repository or GitHub
   Enterprise Cloud; on any other plan every deploy fails closed at this step. A human must
   confirm the plan before the first deploy.
5. **The kubeconfig** comes from `KUBECONFIG_B64`, defined only as a per-Environment secret
   (never at repository or organisation level). It is a namespace-scoped credential.
6. **The migrate Job runs first.** The workflow deletes the previous Job (a Job's pod template is
   immutable), applies the migrate Job with its prerequisites (ConfigMap, NetworkPolicies) and
   none of the workloads, and polls it until it completes. A failed migration, or one that takes
   more than 10 minutes, stops the deploy before any Deployment changes.
7. **Then everything else is applied**, and `kubectl rollout status` checks every Deployment
   of the service; all results are reported before the step fails.

The deploy credential is bound to a namespace-scoped Role that can `get`, `create` and `patch`
ConfigMaps, Services, Deployments, Jobs and NetworkPolicies, `delete` Jobs, `get`, `list` and
`watch` Deployments, `list` Pods and read `pods/log`. It cannot create Namespaces or touch
anything in another namespace. No manifests for the Role, its ServiceAccount or the RoleBinding
are shipped: a cluster admin creates all three by hand, in each namespace, when setting up an
Environment.

## Secrets by reference

No secret is stored in the repository. The manifests reference Secrets by name; whoever operates
the namespace creates them:

| Secret | Keys | Given to |
|---|---|---|
| `ledger-secrets` | `LEDGER_DATABASE_URL` (the `sb_app` role) | API, worker, consumer, migrate Job |
| `ledger-admin-secrets` | `LEDGER_ADMIN_USERNAME`, `LEDGER_ADMIN_PASSWORD`, `LEDGER_ADMIN_SECRET_KEY` (32+ characters) | the `ledger-api` Deployment only, in dev only (the admin is not mounted in prod) |
| `ledger-migrate-secrets` | `LEDGER_MIGRATOR_URL` (BYPASSRLS), `LEDGER_ADMIN_DATABASE_URL` | the `ledger-migrate` Job only |

Non-secret settings (`LEDGER_ENVIRONMENT`, `LEDGER_AUTH_MODE`, hosts) are in the `ledger-config`
ConfigMap, set per overlay. The privileged database URLs never reach a long-running process.

## Prod fails closed until OIDC exists (D1)

The prod overlay sets `LEDGER_ENVIRONMENT=prod` and `LEDGER_AUTH_MODE=oidc`. OIDC is not
implemented: `sb_http.auth.backend_for` raises `NotImplementedError`, and `Settings` refuses dev
auth outside `local`, `dev`, `test` and `ci`. So the prod `ledger-api` Deployment crash-loops, and
`deploy.yml`'s rollout step fails for prod, until OIDC lands. That is intended. Do not stub OIDC,
and never set dev auth in prod. The SQLAdmin is never mounted in prod either, so its credentials
are not needed there.

## Rollback

Re-deploy the previous good SHA with `deploy.yml`: the same gates run and the Deployments roll
back to that image digest. Migrations are expand-then-contract, so the previous release still
works against a schema that has been migrated forward; a destructive schema change is never a
single step. `deploy.yml` never runs a downgrade.

Limit: the migrate Job runs first, and `alembic upgrade head` in an older image cannot find a
revision that only a newer release contains. So rolling back across a release that added a
migration fails at the migrate step, before any Deployment changes (fail closed). The fix is to
roll forward with a corrected commit; if that is not possible, stop and ask a human, because the
schema has to be handled by hand. `make db-downgrade SVC=ledger` is for the local stack only.

## Pinning

The service images' base images (Python, `uv`) and the workflow actions are pinned by digest or
SHA. Not everything is: the local Kafka UI (`ghcr.io/kafbat/kafka-ui:latest`, compose profile
`tools`) is `:latest`. It is a developer tool that never reaches a cluster.
