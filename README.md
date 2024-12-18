# InterLink Kubernetes Plugin

[InterLink](https://intertwin-eu.github.io/interLink/) plugin to extend the capabilities of existing Kubernetes clusters,
enabling them to offload workloads to another remote cluster.
This is particularly useful for distributing workloads across multiple clusters for better resource utilization and fault
tolerance.

## Index

- [InterLink Kubernetes Plugin](#interlink-kubernetes-plugin)
  - [Index](#index)
  - [Configure and Launch](#configure-and-launch)
  - [Microservices Offloading](#microservices-offloading)
  - [Development](#development)

This plugin enables offloading the execution of a POD to a remote Kubernetes cluster.

![InterLink Offloading](docs/assets/diagram-offloading.png)

## Configure and Launch

File [config.sample.ini](src/private/config.sample.ini) defines plugin's configuration,
rename file to *config.ini* and provide missing values, in particular:

- k8s.kubeconfig_path: path to the Kubeconfig yaml file to access the *remote* cluster;
- k8s.kubeconfig: alternatively, provide Kubeconfig inline in json format;
- k8s.client_configuration: options to enable secure client-server communication;
- offloading.namespace_prefix: remote cluster namespace prefix where resources are offloaded;
- offloading.node_selector: remote workloads node selector, if you want to offload resources to selected nodes;
- offloading.node_tolerations: remote workloads node tolerations, if you want to offload resources to tainted nodes.

The following properties are required for the offloading of HTTP Microservices:

- tcp_tunnel.gateway_host: IP of the Gateway host where the Reverse SSH Tunnel will be created
  (see [tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md));
- tcp_tunnel.gateway_port: port to reach the Gateway's SSH daemon;
- tcp_tunnel.gateway_ssh_private_key: the SSH private key

Assuming *config.ini* file is located at path `./private/config.ini` together with additional configuration files
(e.g. `private/k8s/kubeconfig.yaml`), you can launch plugin with:

```sh
docker run --rm -v ./private:/interlink-kubernetes-plugin/private -p 30400:4000 docker.io/mginfn/interlink-kubernetes-plugin:latest uvicorn main:app --host=0.0.0.0 --port=4000 --log-level=debug
```

## Microservices Offloading

This plugin supports the offloading of PODs that expose HTTP endpoints (i.e., HTTP Microservices).

In order to offload an HTTP Microservice, you must declare a TCP port in container's POD definition, e.g.:

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

(see e.g., [test-microservice](src/infr/manifests/test-microservice.yaml)),
then the plugin will setup a TCP Tunnel to forward traffic from the *local* cluster to the *remote* cluster:

![Microservice Offloading](docs/assets/diagram-tunnel.png)

The plugin leverages Helm charts at [tcp-tunnel](src/infr/charts/tcp-tunnel) to install a TCP Tunnel
for secure connections between a pair of Gateway and Bastion hosts.

Notice that the plugin takes care of installing a Bastion host in the *remote* cluster for each offloaded POD,
while you are in charge of installing a Gateway host (single instance) in the *local* cluster
and provide the *tcp_tunnel* config properties to allow the Bastion host to reach the Gateway host.

## Development

Clone repository, then install plugin's dependencies:

```sh
pip install -r src/infr/containers/dev/requirements.txt
```

Launch plugin as follows:

```sh
cd src
python -m uvicorn main:app --host=0.0.0.0 --port=30400
```
