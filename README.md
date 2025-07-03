# InterLink Kubernetes Plugin

[InterLink](https://intertwin-eu.github.io/interLink/) plugin to extend the capabilities of *local* Kubernetes clusters,
enabling them to offload workloads to other *remote* clusters.
This is particularly useful for distributing workloads across multiple clusters for better resource utilization and fault
tolerance.

![InterLink Offloading](docs/assets/diagram-offloading.png)

## Index

- [InterLink Kubernetes Plugin](#interlink-kubernetes-plugin)
  - [Index](#index)
  - [How to Run](#how-to-run)
    - [Configure](#configure)
    - [Docker Run](#docker-run)
    - [Development](#development)
    - [Install via Ansible role](#install-via-ansible-role)
  - [Features](#features)
    - [POD's Volumes](#pods-volumes)
    - [Microservices Offloading](#microservices-offloading)
  - [Troubleshooting](#troubleshooting)
    - [401 Unauthorized](#401-unauthorized)
    - [certificate verify failed: unable to get local issuer certificate](#certificate-verify-failed-unable-to-get-local-issuer-certificate)
  - [Credits](#credits)

## How to Run

### Configure

File [config.sample.ini](src/private/config.sample.ini) defines plugin's configuration,
rename file to *config.ini* and provide missing values, in particular:

- k8s.kubeconfig_path: path to the Kubeconfig YAML file to access the *remote* cluster, defaults to `./private/k8s/kubeconfig.yaml`;
- k8s.kubeconfig: alternatively, provide Kubeconfig inline in json format;
- k8s.client_configuration: options to set to the underlying python Kubernetes client
  [configuration object](https://github.com/kubernetes-client/python/blob/master/kubernetes/client/configuration.py);
- offloading.namespace_prefix: remote cluster namespace prefix where resources are offloaded, defaults to `offloading`;
- offloading.node_selector: remote workloads node selector, if you want to offload resources to selected nodes;
- offloading.node_tolerations: remote workloads node tolerations, if you want to offload resources to tainted nodes.

The following properties are required for the offloading of HTTP Microservices
(see [tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md)):

- tcp_tunnel.gateway_host: IP of the Gateway host where the Reverse SSH Tunnel will be created;
- tcp_tunnel.gateway_port: port to reach the Gateway's SSH daemon;
- tcp_tunnel.gateway_ssh_private_key: the SSH private key

See [Troubleshooting](#troubleshooting) below for common errors.

### Docker Run

Docker images are currently hosted at [hub.docker.com/r/mginfn/interlink-kubernetes-plugin](https://hub.docker.com/r/mginfn/interlink-kubernetes-plugin).
Assuming your *config.ini* file is located at path `./private/config.ini` together with additional configuration files
(e.g. `./private/k8s/kubeconfig.yaml`), you can launch the plugin with:

```sh
docker run --rm -v ./private:/interlink-kubernetes-plugin/private -p 30400:4000 docker.io/mginfn/interlink-kubernetes-plugin:latest uvicorn main:app --host=0.0.0.0 --port=4000 --log-level=debug
```

### Development

Clone repository, then install plugin's dependencies:

```sh
pip install -r src/infr/containers/dev/requirements.txt
```

Create *config.ini* file as described above, then launch plugin as follows:

```sh
cd src
python -m uvicorn main:app --host=0.0.0.0 --port=30400
```

### Install via Ansible role

See [Ansible Role InterLink > In-cluster](https://baltig.infn.it/infn-cloud/ansible-role-interlink#in-cluster)
to install InterLink components together with the Kubernetes Plugin
in a running Kubernetes cluster.

## Features

### POD's Volumes

The plugin supports the offloading of PODs that reference volumes (via `spec.volumes`)
and mount them (via `spec.containers[*].volumeMounts`) for the following types:

- configMap
- secret
- emptyDir
- persistenVolumeClaim

In particular, when a POD is offloaded, the referenced **configMaps** and **secrets** are offloaded
as well, i.e. they are created in the remote cluster with the same content they have in the local cluster
(notice that their names keep the original name + POD's uid).
When the POD is deleted from the local cluster, the referenced **configMaps** and **secrets** are deleted
from the remote cluster as well.

Regarding **persistentVolumeClaims**, the behaviour is similar: when the POD is offloaded,
the referenced PVC will be offloaded as whell, i.e. the PVC will be created in the remote cluster
(except if it doesn't exist already).
Provide the following annotations to control the behaviour:

- `interlink.io/remote-pvc`: add this annotation to POD metadata to provide a comma-separated list of
  PVC names that will be offloaded;
- `interlink.io/pvc-retention-policy`: either "delete" or "retain", add this annotation to the PVC
  metadata to either delete or retain it when the POD referencing it will be deleted.

An example manifest is provided here: [test-pod-pvc.yaml](src/infr/manifests/test-pod-pvc.yaml).
Notice that since the POD is submitted to the local cluster, the PVC must exist in the local cluster as well,
otherwise Kubernetes won't schedule it on the VirtualNode (and the POD won't be offloaded).

Note: current PVC support is experimental and it's not yet supported by InterLink API Server,
see issue [Add support for POD's PersistentVolumeClaims](https://github.com/interlink-hq/interLink/issues/396).

### Microservices Offloading

The plugin supports the offloading of PODs that expose HTTP endpoints (i.e., HTTP Microservices).

When offloading an HTTP Microservice, you must explicitly declare the TCP ports in container's POD definition,
see e.g., [test-microservice](src/infr/manifests/test-microservice.yaml):

```yaml
apiVersion: v1
kind: Pod
metadata:
  ...
spec:
  containers:
  - name: test-container
    ...
    ports:
      - containerPort: 8181
        protocol: TCP
```

then the plugin will setup a TCP Tunnel to forward traffic from the *local* cluster to the *remote* cluster.

I.e., the plugin leverages Helm charts (see [tcp-tunnel](src/infr/charts/tcp-tunnel)) to install a TCP Tunnel
for secure connections between a pair of Gateway and Bastion hosts:

![Microservice Offloading](docs/assets/diagram-tunnel.png)

Notice that the plugin takes care of installing a Bastion host in the *remote* cluster for each offloaded POD,
while you are in charge of installing a Gateway host (single instance) in the *local* cluster
and provide to the plugin the *tcp_tunnel* config properties to allow the Bastion host to reach the Gateway host
to start the tunnel.

## Troubleshooting

### 401 Unauthorized

If the plugin raises error "401 Unauthorized", check the **remote** cluster Kubeconfig YAML.

The `cluster` section must include the URL of the Kubernetes API Server and the inline base64-encoded CA certificate:

```yaml
clusters:
- cluster:
    certificate-authority-data: <base64-encoded-CA-certificate>
    server: https://example.com:6443
  name: my-cluster
```

alternatively, you can provide the path to the CA certificate, but you must take care of allowing the plugin
to read that file (e.g., you need to mount a volume when running the docker image):

```yaml
clusters:
- name: cluster-name
  cluster:
    certificate-authority: /path/to/ca.crt
    server: https://example.com:6443
```

finally, you can disable certificate verification (but you will get "InsecureRequestWarning" in plugin's logs):

```yaml
clusters:
- cluster:
    insecure-skip-tls-verify: true
    server: https://example.com:6443
  name: my-cluster
```

Regarding the `users` section, you must include the inline base64-encoded client certificate and key:

```yaml
users:
- name: admin
  user:
    client-certificate-data: <base64-encoded-certificate>
    client-key-data: <base64-encoded-key>
```

alternatively, you can provide the path to the client certificate and key, but you must take care of allowing the plugin
to read that files:

```yaml
users:
- name: admin
  user:
    client-certificate: /path/to/client.crt
    client-key: /path/to/client.key
```

finally, token-based authentication is also allowed, e.g.:

```yaml
users:
- name: admin
  user:
    token: <auth-token>
```

### certificate verify failed: unable to get local issuer certificate

If the plugin raises error
"certificate verify failed: unable to get local issuer certificate"
while attempting to access the remote cluster,
it likely indicates that your Kubernetes cluster is using self-signed x509 certificates.
Check the client and CA certificates in the Kubeconfig YAML file to confirm.

You can fix either disabling certificate verification at all:

- k8s.client_configuration={"verify_ssl": false}

or explicitly providing the x509 certificates and client private key:

- k8s.client_configuration={"verify_ssl": true, "ssl_ca_cert": "private/k8s-microk8s/ca.crt", "cert_file": "private/k8s-microk8s/client.crt", "key_file": "private/k8s-microk8s/client.key"}

## Credits

Originally created by Mauro Gattari in 2024.
