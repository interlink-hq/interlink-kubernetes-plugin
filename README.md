# InterLink Kubernetes Plugin

[InterLink](https://intertwin-eu.github.io/interLink/) plugin to extend the capabilities of *local* Kubernetes
clusters by offloading workloads to *remote* clusters.

![InterLink Offloading](docs/assets/diagram-offloading.png)

## Index

- [InterLink Kubernetes Plugin](#interlink-kubernetes-plugin)
  - [Index](#index)
  - [Prerequisites](#prerequisites)
  - [How to Run](#how-to-run)
    - [Configure](#configure)
    - [Docker Run](#docker-run)
    - [Development Run](#development-run)
    - [Install via Ansible role](#install-via-ansible-role)
  - [API Endpoints](#api-endpoints)
  - [Features](#features)
    - [InterLink Mesh Networking](#interlink-mesh-networking)
    - [Pod Volumes](#pod-volumes)
    - [Microservices Offloading (Deprecated)](#microservices-offloading-deprecated)
  - [Troubleshooting](#troubleshooting)
    - [401 Unauthorized](#401-unauthorized)
    - [TLS verify failed](#tls-verify-failed)
  - [Credits](#credits)

## Prerequisites

- Python 3.12 (for local development)
- Docker (for containerized runtime)
- Access to a remote Kubernetes cluster (`kubeconfig`)
- Helm CLI only if using the deprecated TCP tunnel feature

## How to Run

### Configure

`src/private/config.sample.ini` defines the plugin configuration.
Create `config.ini` from it and provide your environment values:

```sh
cp src/private/config.sample.ini src/private/config.ini
```

Key properties:

- `k8s.kubeconfig_path`: path to kubeconfig for the *remote* cluster (default: `private/k8s/kubeconfig.yaml`),
  see the [Troubleshooting](#troubleshooting) section for common errors
- `k8s.kubeconfig`: optional inline kubeconfig as JSON
- `k8s.client_configuration`: optional JSON passed to Kubernetes Python client configuration,
  see [configuration object](https://github.com/kubernetes-client/python/blob/master/kubernetes/client/configuration.py)
- `offloading.namespace_prefix`: prefix for offloaded namespaces (default: `offloading`)
- `offloading.namespace_prefix_exclusions`: namespaces excluded from prefixing
- `offloading.node_selector`: optional selector JSON applied to offloaded pods
- `offloading.node_tolerations`: optional tolerations JSON applied to offloaded pods

By default, config is read from `src/private/config.ini`. You can override this with `CONFIG_FILE_PATH`.

### Docker Run

Images are currently published at
[hub.docker.com/r/mginfn/interlink-kubernetes-plugin](https://hub.docker.com/r/mginfn/interlink-kubernetes-plugin).

If your config files are under `./src/private`:

```sh
docker run --rm \
  -v ./src/private:/interlink-kubernetes-plugin/private \
  -p 30400:4000 \
  docker.io/mginfn/interlink-kubernetes-plugin:latest \
  uvicorn main:app --host=0.0.0.0 --port=4000 --log-level=debug
```

### Development Run

Install dependencies:

```sh
pip install -r src/infr/containers/dev/requirements.txt
```

Start the API server:

```sh
cd src
python -m uvicorn main:app --host=0.0.0.0 --port=30400 --log-level=debug
```

### Install via Ansible role

See [Ansible Role InterLink > In-cluster](https://baltig.infn.it/infn-cloud/ansible-role-interlink#in-cluster)
to install InterLink components together with this Kubernetes Plugin in a running cluster.

## API Endpoints

The v1 controller exposes:

- `GET /status`
- `GET /getLogs`
- `POST /create`
- `POST /delete`

Interactive docs are available at `/docs` (configurable via `app.api_docs_path`).

## Features

### InterLink Mesh Networking

The plugin supports
[Interlink Mesh Networking](https://github.com/interlink-hq/interLink/blob/474-improve-documentation-for-mesh-networking-feature/docs/docs/guides/13-mesh-network-configuration.mdx)
to allow pods running on the **remote** cluster to communicate with services and pods in the **local** cluster.

### Pod Volumes

Note: this feature is experimental and may be subject to breaking changes.

The plugin supports offloading pods that reference `spec.volumes` and mount them with
`spec.containers[*].volumeMounts` for:

- `configMap`
- `secret`
- `emptyDir`
- `persistentVolumeClaim`

Behavior summary:

- referenced `ConfigMap` and `Secret` objects are offloaded and scoped to the pod UID
  (i.e., their names are suffixed with POD's uid)
- when the offloaded pod is deleted, scoped `ConfigMap` and `Secret` objects are deleted as well
- PVC offloading is enabled per pod using metadata annotation `interlink.io/remote-pvc`
  (comma-separated list of PVC names that will be offloaded)
- PVC cleanup policy is controlled by PVC annotation `interlink.io/pvc-retention-policy` (`delete` or `retain`)

See example manifest: [test-pod-pvc.yaml](src/infr/manifests/test-pod-pvc.yaml).

Notes:

- that since the POD is submitted to the local cluster, the PVC must exist in the local cluster as well,
  otherwise Kubernetes won't schedule it on the VirtualNode (and the POD won't be offloaded)
  current PVC support is experimental and not yet supported by InterLink API Server.
See [interlink-hq/interLink#396](https://github.com/interlink-hq/interLink/issues/396).

### Microservices Offloading (Deprecated)

Note: this feature is deprecated and may be removed in future releases. It is recommended to use
InterLink Mesh Networking instead.

The plugin supports offloading HTTP microservices through TCP tunnel Helm charts:
[src/infr/charts/tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md).

To enable this feature, configure in `config.ini`:

- `tcp_tunnel.gateway_host`: gateway host IP/DNS
- `tcp_tunnel.gateway_port`: gateway SSH port
- `tcp_tunnel.gateway_ssh_private_key`: SSH private key

For offloaded microservices, explicitly declare container TCP ports in pod specs.
See [test-microservice.yaml](src/infr/manifests/test-microservice.yaml).

![Microservice Offloading](docs/assets/diagram-tunnel.png)

The plugin installs a Bastion release in the *remote* cluster for each offloaded pod.
You must install and expose one Gateway instance in the *local* cluster.

## Troubleshooting

### 401 Unauthorized

If the plugin raises `401 Unauthorized`, check the **remote** kubeconfig.

The `cluster` section must include the URL of the Kubernetes API Server and the inline base64-encoded CA certificate:

```yaml
clusters:
- cluster:
    certificate-authority-data: <base64-encoded-CA-certificate>
    server: https://api-kubernetes.example.com
  name: my-cluster
```

Alternatively, provide a CA certificate path and ensure it is readable by the plugin:

```yaml
clusters:
- name: cluster-name
  cluster:
    certificate-authority: /path/to/ca.crt
    server: https://api-kubernetes.example.com
```

You can disable server certificate verification (but you will get "InsecureRequestWarning" in plugin's logs):

```yaml
clusters:
- cluster:
    insecure-skip-tls-verify: true
    server: https://api-kubernetes.example.com
  name: my-cluster
```

In the `users` section, include client certificate/key or token authentication:

```yaml
users:
- name: admin
  user:
    client-certificate-data: <base64-encoded-certificate>
    client-key-data: <base64-encoded-key>
```

Or file paths:

```yaml
users:
- name: admin
  user:
    client-certificate: /path/to/client.crt
    client-key: /path/to/client.key
```

Or token-based authentication:

```yaml
users:
- name: admin
  user:
    token: <auth-token>
```

### TLS verify failed

If the plugin raises
`certificate verify failed: unable to get local issuer certificate` while reaching the remote cluster,
your cluster may use self-signed certificates.

You can disable certificate verification:

- `k8s.client_configuration={"verify_ssl": false}`

Or explicitly provide CA/client certificates:

- `k8s.client_configuration={"verify_ssl": true, "ssl_ca_cert": "private/k8s-microk8s/ca.crt",`
  `"cert_file": "private/k8s-microk8s/client.crt", "key_file": "private/k8s-microk8s/client.key"}`

## Credits

Originally created by Mauro Gattari @ INFN in 2024.
