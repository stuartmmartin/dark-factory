# ADR-0013: Kustomize base + overlays, no Argo CD yet

- **Status:** Accepted
- **Date:** 2026-09-28

## Context
Services need to be deployed to Kubernetes for at least `dev` and `prod` environments, with
per-environment differences in replicas, resources, image tag and namespace (spec §9.1). The
options were a templating tool (Helm), a GitOps controller (Argo CD/Flux) reconciling against a
git repo, or Kustomize's base-plus-overlay patching applied directly from CI. For a 3–5 person
team not yet running a GitOps loop, a templating language and/or a cluster-side controller are
additional systems to operate and debug for a benefit (progressive delivery, drift reconciliation)
that isn't yet needed.

## Decision
Kubernetes manifests are plain, readable YAML under `deploy/k8s/<svc>/{base, overlays/{dev,prod}}`,
composed with Kustomize (no Helm templating language). `make k8s-render` runs `kustomize build` and
CI validates the output with `kubeconform`. Deploys are pushed by `deploy.yml`
(`workflow_dispatch`): `kustomize edit set image` then `kubectl apply -k …`, with the migration
Job required to succeed before the Deployments roll out, and a required reviewer gating `prod`
(spec §9). No Argo CD or Flux is introduced.

## Consequences
Anyone can read the exact manifests that will be applied with no templating engine to mentally
evaluate, and `kubeconform` catches malformed YAML before it reaches a cluster. The cost is that
there is no continuous reconciliation loop watching for drift between the cluster and git — if
someone `kubectl edit`s a live resource, nothing notices or reverts it until the next
`workflow_dispatch` deploy, and there's no automatic rollback or progressive-delivery machinery.

## Revisit when
The team needs GitOps properties — drift detection/auto-heal, progressive rollout, or multiple
clusters reconciling from the same source of truth without a human triggering each deploy — at
which point Argo CD/Flux can be layered on top of the same Kustomize manifests without rewriting
them.
