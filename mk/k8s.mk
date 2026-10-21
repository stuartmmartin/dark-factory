# Kubernetes manifests (Kustomize). Overlays live at deploy/k8s/<svc>/overlays/<env>.
# kustomize and kubeconform are pinned in mise.toml (`make bootstrap`); without mise on PATH they
# run through `mise exec`.
.PHONY: k8s-render k8s-validate

MISE_EXEC := $(if $(shell command -v kustomize 2>/dev/null),,mise exec --)
KUSTOMIZE ?= $(MISE_EXEC) kustomize
KUBECONFORM ?= $(MISE_EXEC) kubeconform
K8S_OVERLAYS = $(patsubst %/kustomization.yaml,%,$(wildcard deploy/k8s/*/overlays/*/kustomization.yaml))
# The cluster-admin-only set (Namespaces with their Pod Security labels) is validated too.
K8S_SETS = $(wildcard deploy/k8s/cluster-admin) $(K8S_OVERLAYS)

k8s-render: ## Render one overlay: make k8s-render SVC=ledger ENV=dev
	@test -n "$(SVC)" -a -n "$(ENV)" || { echo "usage: make k8s-render SVC=<service> ENV=<dev|prod>"; exit 2; }
	@test -f "deploy/k8s/$(SVC)/overlays/$(ENV)/kustomization.yaml" || { echo "no overlay deploy/k8s/$(SVC)/overlays/$(ENV)"; exit 2; }
	@$(KUSTOMIZE) build deploy/k8s/$(SVC)/overlays/$(ENV)

k8s-validate: ## Render every overlay (and deploy/k8s/cluster-admin) and validate it against the Kubernetes schemas (kubeconform)
	@test -n "$(K8S_OVERLAYS)" || { echo "no overlays under deploy/k8s/*/overlays/"; exit 2; }
	@set -eu; \
	rendered=$$(mktemp); trap 'rm -f "$$rendered"' EXIT; \
	for o in $(K8S_SETS); do \
		echo "== $$o"; \
		$(KUSTOMIZE) build "$$o" > "$$rendered" || exit 1; \
		grep -Eq '^[[:space:]]*kind:' "$$rendered" || { echo "empty render (no resources): $$o" >&2; exit 1; }; \
		$(KUBECONFORM) -strict -summary - < "$$rendered" || exit 1; \
	done
