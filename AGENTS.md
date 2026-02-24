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
- `test/infr/manifests/*`: manual test manifests

## Core implementation foundations

These are the code-level foundations that shape how this plugin works today.

1. Runtime composition and dependency graph:
  `microservice.py` initializes config and logger through `dependencies.py`, loads controllers from configured API versions,
  registers global exception handlers, and wires optional request logging middleware from config.
  `dependencies.py` owns singleton construction for `Config`, logger, `KubernetesPluginService` and third-party clients.
2. Controller-to-service contract:
  `KubernetesPluginController` is intentionally thin and async. Endpoints delegate directly to
  `KubernetesPluginService`.
3. Model translation boundary:
  InterLink-to-Kubernetes and Kubernetes-to-InterLink conversion is centralized in `entities/mappers.py`.
  Service code relies on these mappers instead of manual nested dict/object conversions.
4. Resource scoping and traceability model:
  `KubernetesPluginService` scopes target namespace and object names (`_scope_ns_name`, `_scope_obj_name`) and
  sanitizes names for RFC1123 compliance (`_ensure_subdomain_compliance`).
  `_scope_metadata` injects traceability labels/annotations (`interlink.io/source.*`, `interlink.io/source.pod_uid`)
  that tie remote resources back to the original pod.
5. Offloading lifecycle orchestration:
  `create_pod` follows a strict sequence: ensure namespace, create supported dependent volumes/resources,
  then create the remote pod. Failures trigger rollback through `delete_pod(..., rollback=True)`.
  Deletion is best-effort and cleanup-oriented: pod first, then tunnel resources, then scoped ConfigMaps/Secrets/PVCs.
6. Volume and PVC policy:
  `_filter_volumes` keeps only supported volume types (`configMap`, `secret`, `emptyDir`, selected PVCs) and rewrites
  related references in `volumeMounts`, `env.valueFrom`, and `envFrom`.
  PVC offloading is opt-in via `interlink.io/remote-pvc`; PVC deletion honors
  `interlink.io/pvc-retention-policy`.
7. Networking feature paths:
  Mesh support is implemented by parsing `slurm-job.vk.io/pre-exec`, extracting heredoc content, and injecting setup
  containers/volumes based on mesh config flags.
  TCP tunnel logic is deprecated but still active; install/uninstall flow must remain symmetric to avoid orphaned
  Helm releases and Services.

## Configuration rules

- Config precedence is: programmatic overrides -> env vars -> `config.ini`.
- When adding config keys:
  - add `Option` enum in `src/app/common/config.py`
  - wire behavior in `dependencies.py` / service layer
  - document in `src/private/config.sample.ini`
  - document in `README.md`

## Agent coding playbook

Use this checklist when implementing or reviewing code changes.

1. Place changes in the right layer:
  keep request/response orchestration in controllers, implementation in services, object translation in mappers,
  and wiring in dependencies/config.
2. Preserve scoping and metadata semantics:
  any new namespaced or pod-related resource must use the existing scoping helpers and keep InterLink traceability
  labels/annotations consistent.
3. Keep lifecycle operations rollback-safe:
  if adding new resources in create flows, add matching cleanup in delete/rollback flows and handle partial failure
  without breaking cleanup of remaining resources.
4. Respect volume handling rules:
  when introducing new volume-related logic, ensure references are consistently updated across pod spec sections
  and cleanup behavior remains predictable.
5. Follow config extension workflow:
  add new keys to `Option`, consume them in service/dependencies, and update both
  `src/private/config.sample.ini` and `README.md`.
6. Keep API compatibility stable:
  maintain existing endpoint contracts and InterLink model shapes unless the change explicitly includes an API change.
7. Logging and errors:
  log resource operations with resource name/namespace context, prefer structured actionable error messages, and keep
  error responses JSON-compatible through existing exception handling paths.

## Docs sync checklist

If behavior changes, update all relevant docs together:

- `README.md` (user-facing setup/feature behavior)
- `src/private/config.sample.ini` (config defaults/options)
- `test/infr/manifests/*` (example manifests)
