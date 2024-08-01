
InterLink plugin to offload the execution of a POD to a *remote* cluster.
The plugin supports the offloading of PODs that implements HTTP microservices: a TCP Tunnel is setup to forward traffic from the *local* cluster to the *remote* cluster.

# Index

- [Index](#index)
- [TODO](#todo)
- [InterLink Kubernetes Plugin](#interlink-kubernetes-plugin)
- [TCP-Tunnel Helm Charts](#tcp-tunnel-helm-charts)
  - [Install](#install)
    - [Install Gateway](#install-gateway)
    - [Install Bastion](#install-bastion)
    - [Check tunnel](#check-tunnel)

# TODO

- [ ] Add documentation to setup InterLink Kubernetes Plugin environment.
- [ ] Write script to build docker image to run plugin.
- [ ] Troubleshoot `pyhelm3` error when installing bastion with `install_or_upgrade_release()`.
- [ ] Open issue to add `containerPort` support in InterLink `PodRequest` class, see `KubernetesPluginService::_get_container_ports()`.
- [ ] Integrate [gateway](src/infr/charts/tcp-tunnel/charts/gateway) Helm chart in VirtualKubelet (?).
- [ ] Automate the SSH key pair generation and installation (?).

# InterLink Kubernetes Plugin

Launch InterLink Kubernetes Plugin as follows:
```sh
python -m uvicorn main:app --host=0.0.0.0 --port=30400
```

# TCP-Tunnel Helm Charts

As part of this plugin's development, Helm chart [tcp-tunnel](src/infr/charts/tcp-tunnel) allows to install a TCP Tunnel for secure connections between a pair of Gateway and Bastion hosts.

## Install

Generate an SSH key pair:
```sh
ssh-keygen -t rsa -b 4096 -C "interlink-gateway-key" -f ./private/ssh/id_rsa
# Base64 encoding of private key:
base64 --wrap 0 ./private/ssh/id_rsa
```

Helm chart [tcp-tunnel](src/infr/charts/tcp-tunnel) includes two subcharts to be installed **separately**:
- chart `gateway` to be installed on the *local* cluster
- `bastion` chart to be installed on the *remote* cluster

A single release of chart `gateway` is installed by the VirtualKubelet running in the *local* cluster and will handle multiple TCP tunnels.
For each pod offloading request, a chart `bastion` release is installed by the InterLink Kubernetes Plugin in the *remote* cluster to setup a TCP tunnel.

### Install Gateway

Install Gateway in the *local* cluster.

**Example.**

Install release `gateway`:
```sh
helm install gateway ./infr/charts/tcp-tunnel/charts/gateway \
    --namespace tcp-tunnel --create-namespace \
    --set ssh.publicKey="$(cat ./private/ssh/id_rsa.pub)" \
    --dry-run --debug
```

The command above deploys a Gateway pod that listens for SSH connections on port 2222, moreover a public port 30222 is exposed through a NodePort; see [values.yaml](src/infr/charts/tcp-tunnel/charts/gateway/values.yaml) for all parameters and default values. The Bastion pod will connect to that port to create a Reverse SSH tunnel.

For development purposes, you can specify `tunnel.service.*` parameters to additionally deploy a NodePort `sourceNodePort` that forwards traffic to Gateway port `sourcePort`: assuming a reverse tunnel from `sourcePort` has been created, this setup can be used to send external TCP traffic to `sourceNodePort` and test the tunnel:
```sh
helm install gateway ./infr/charts/tcp-tunnel/charts/gateway \
    --namespace tcp-tunnel --create-namespace \
    --set ssh.publicKey="$(cat ./private/ssh/id_rsa.pub)" \
    --set tunnel.service.sourcePort=8181 \
    --set tunnel.service.sourceNodePort=30181 \
    --dry-run --debug
```

> **Note:** option `--dry-run --debug` returns the generated template without submitting it.

### Install Bastion

Install Bastion in the *remote* cluster.

**Example.**

Install release `bastion`:
```sh
GATEWAY_HOST=131.154.98.96
SERVICE_HOST=test-pod-2b69e438-52e6-400c-8979-570b14857e1b.interlink-offloading-default.pod.cluster.local
helm install bastion ./infr/charts/tcp-tunnel/charts/bastion \
    --namespace tcp-tunnel --create-namespace \
    --set tunnel.gateway.host=${GATEWAY_HOST} \
    --set tunnel.gateway.ssh.privateKey=$(base64 --wrap 0 ./private/ssh/id_rsa ) \
    --set tunnel.service.gatewayPort=8181 \
    --set tunnel.service.targetHost=${SERVICE_HOST} \
    --set tunnel.service.targetPort=80 \
    --dry-run --debug
```

### Check tunnel

Check whether TCP port 30181 is open on ${GATEWAY_HOST}:
```sh
nc -zv ${GATEWAY_HOST} 30181
```

Then check whether traffic from ${GATEWAY_HOST}:30181 (*local* cluster) is forwarded to ${SERVICE_HOST}:80 in *remote* cluster.
```sh
curl --location "http://${GATEWAY_HOST}:30181/v1/models/mlaas-inference-service-hep"
```
