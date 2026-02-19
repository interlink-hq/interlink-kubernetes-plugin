# AGENTS.md

## Project's Scope

[InterLink](https://github.com/interlink-hq/interLink) is a framework for executing Kubernetes pods on remote resources
capable of managing container execution lifecycles. It consists of two main components:

- Virtual Kubelet (Virtual Node): translates Kubernetes pod execution requests into remote calls to the InterLink API server
- InterLink API Server: a modular, pluggable REST server with provider-specific plugins for different execution environments

This repository implements an InterLink plugin for Kubernetes, which allows offloading pods from a local Kubernetes cluster
to a remote Kubernetes cluster.

The plugin's core responsibilities include  :

- FastAPI service that receives InterLink API requests
- Kubernetes offloading logic (pods, volumes, logs, cleanup)
- Optional TCP tunnel provisioning through Helm charts (deprecated)

## Repository map

- `src/main.py`: ASGI import point (`app`)
- `src/app/microservice.py`: FastAPI app setup, middleware, exception handlers, router loading
- `src/app/controllers/v1/kubernetes_plugin_controller.py`: HTTP endpoints
- `src/app/services/kubernetes_plugin_service.py`: core offloading logic
- `src/app/dependencies.py`: DI wiring and Kubernetes/Helm client provisioning
- `src/app/common/config.py`: config options
- `src/app/entities/mappers.py`: InterLink <-> Kubernetes model mapping
- `src/private/config.sample.ini`: baseline runtime configuration
- `src/infr/charts/tcp-tunnel/*`: gateway/bastion Helm charts (deprecated)
- `src/infr/manifests/*`: manual test manifests

## Runtime architecture

1. `microservice.py` loads config and dependencies, then loads versioned controllers.
2. Controller methods delegate directly to `KubernetesPluginService`.
3. Service maps InterLink models to Kubernetes client models.
4. The service writes to a remote cluster with `CoreV1Api`;

## Critical invariants

Preserve these behaviors unless explicitly requested otherwise.

1. Namespace scoping:
`offloading.namespace_prefix` is applied by `_scope_ns_name`, except namespaces listed in
`offloading.namespace_prefix_exclusions`.
2. Object name scoping:
pod-related object names are suffixed with pod UID and sanitized to RFC1123 using
`_ensure_subdomain_compliance`.
3. Traceability metadata:
`_scope_metadata` must keep `interlink.io/source.*` annotations and `interlink.io/source.pod_uid` label.
4. Volume handling:
only `configMap`, `secret`, `emptyDir`, and selected PVCs are retained in `_filter_volumes`.
5. PVC offloading/deletion:
PVC offloading requires pod annotation `interlink.io/remote-pvc`; deletion behavior depends on
`interlink.io/pvc-retention-policy`.
6. Rollback on create failures:
`create_pod` must trigger `delete_pod(..., rollback=True)` on failures.
7. TCP tunnel behavior:
feature is deprecated but supported; changes must keep uninstall/install symmetry and avoid orphaned resources.

## Configuration rules

- Config precedence is: programmatic overrides -> env vars -> `config.ini`.
- When adding config keys:
  - add `Option` enum in `src/app/common/config.py`
  - wire behavior in `dependencies.py` / service layer
  - document in `src/private/config.sample.ini`
  - document in `README.md`

## Coding conventions

- Keep controllers thin; business logic belongs in services.
- Reuse `mappers.py` for InterLink/Kubernetes model conversion.
- Keep async endpoint signatures and return types consistent with `interlink` SDK models.
- Avoid destructive Kubernetes operations outside existing flow and safeguards.
- Keep logging informative and structured around resource name/namespace.

## Docs sync checklist

If behavior changes, update all relevant docs together:

- `README.md` (user-facing setup/feature behavior)
- `src/private/config.sample.ini` (config defaults/options)
- `src/infr/manifests/*` (example manifests)
