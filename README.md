# InterLink Kubernetes Plugin

[InterLink](https://intertwin-eu.github.io/interLink/) plugin to extend the capabilities of existing Kubernetes clusters,
enabling them to offload workloads to another remote cluster.
This is particularly useful for distributing workloads across multiple clusters for better resource utilization and fault
tolerance.

![InterLink Offloading](docs/assets/diagram-offloading.png)

## Index

- [InterLink Kubernetes Plugin](#interlink-kubernetes-plugin)
  - [Index](#index)
  - [How to Run](#how-to-run)
    - [Configure](#configure)
    - [Docker Run](#docker-run)
    - [Local Run](#local-run)
    - [Install via Ansible role](#install-via-ansible-role)
  - [Microservices Offloading](#microservices-offloading)
  - [Troubleshooting](#troubleshooting)
    - [certificate verify failed: unable to get local issuer certificate](#certificate-verify-failed-unable-to-get-local-issuer-certificate)

## How to Run

### Configure

File [config.sample.ini](src/private/config.sample.ini) defines plugin's configuration,
rename file to *config.ini* and provide missing values, in particular:

- k8s.kubeconfig_path: path to the Kubeconfig YAML file to access the *remote* cluster, defaults to `private/k8s/kubeconfig.yaml`;
- k8s.kubeconfig: alternatively, provide Kubeconfig inline in json format;
- k8s.client_configuration: options to enable/disable secure client-server communication;
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

Assuming *config.ini* file is located at path `./private/config.ini` together with additional configuration files
(e.g. `private/k8s/kubeconfig.yaml`), you can launch the plugin with:

```sh
docker run --rm -v ./private:/interlink-kubernetes-plugin/private -p 30400:4000 docker.io/mginfn/interlink-kubernetes-plugin:latest uvicorn main:app --host=0.0.0.0 --port=4000 --log-level=debug
```

### Local Run

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

## Microservices Offloading

The plugin supports the offloading of PODs that expose HTTP endpoints (i.e., HTTP Microservices).

When offloading an HTTP Microservice, you must explicitly declare at least a TCP port in container's POD definition,
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

I.e., the plugin leverages Helm charts [tcp-tunnel](src/infr/charts/tcp-tunnel) to install a TCP Tunnel
for secure connections between a pair of Gateway and Bastion hosts:

![Microservice Offloading](docs/assets/diagram-tunnel.png)

Notice that the plugin takes care of installing a Bastion host in the *remote* cluster for each offloaded POD,
while you are in charge of installing a Gateway host (single instance) in the *local* cluster
and provide to the plugin the *tcp_tunnel* config properties to allow the Bastion host to reach the Gateway host
to start the tunnel.

## Troubleshooting

### certificate verify failed: unable to get local issuer certificate

If the plugin raises the error
"certificate verify failed: unable to get local issuer certificate"
while attempting to access the remote cluster,
it likely indicates that your Kubernetes cluster is using self-signed x509 certificates.
Check the client and CA certificates in the Kubeconfig YAML file to confirm.

You can fix either disabling certificate verification at all:

- k8s.client_configuration={"verify_ssl": false}

or explicitly providing the x509 certificates and client private key:

- k8s.client_configuration={"verify_ssl": true, "ssl_ca_cert": "private/k8s-microk8s/ca.crt", "cert_file": "private/k8s-microk8s/client.crt", "key_file": "private/k8s-microk8s/client.key"}
