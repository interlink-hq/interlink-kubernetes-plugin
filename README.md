InterLink plugin to extend the capabilities of existing Kubernetes clusters, enabling them to offload workloads to another remote cluster. This is particularly useful for distributing workloads across multiple clusters for better resource utilization and fault tolerance.

# Index

- [Index](#index)
- [Description](#description)
- [Setup and Launch](#setup-and-launch)
- [TCP-Tunnel Helm Charts](#tcp-tunnel-helm-charts)

# Description

This plugin enables offloading the execution of a POD to a remote cluster.
It supports the offloading of PODs that expose HTTP endpoints (i.e., HTTP Microservices):

![Microservice Offloading](docs/assets/diagram-offloading.png)

In order to offload an HTTP Microservice, ensure to declare a TCP port in container's deployment definition (see e.g., [test-microservice](src/infr/manifests/test-microservice.yaml)), then the plugin will setup a TCP Tunnel to forward traffic from the *local* cluster to the *remote* cluster:

![Microservice Offloading](docs/assets/diagram-tunnel.png)

# Setup and Launch

File [config.sample.ini](src/private/config.sample.ini) defines plugin's configuration, rename file to *config.ini* and provide missing values, in particular:
- k8s.kubeconfig_path: path to the Kubeconfig yaml file to access the *remote* cluster
- tcp_tunnel.gateway_host: IP of the Gateway host where the Reverse SSH Tunnel will be created (See [tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md))
- tcp_tunnel.gateway_port: port to reach the Gateway's SSH daemon
- tcp_tunnel.gateway_ssh_private_key: the SSH private key

Install InterLink Kubernetes Plugin's dependencies:
```sh
pip install -r src/infr/containers/dev/requirements.txt
```

Launch plugin as follows:
```sh
cd src
python -m uvicorn main:app --host=0.0.0.0 --port=30400
```

# TCP-Tunnel Helm Charts

This plugin leverages Helm chart [tcp-tunnel](src/infr/charts/tcp-tunnel) to install a TCP Tunnel for secure connections between a pair of Gateway and Bastion hosts.

See [tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md)
