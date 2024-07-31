
# Index

- [Index](#index)
- [InterLink Kubernetes Plugin](#interlink-kubernetes-plugin)
- [TCP-Tunnel Helm Chart](#tcp-tunnel-helm-chart)
  - [Install](#install)
    - [Install Gateway](#install-gateway)
    - [Install Bastion](#install-bastion)
    - [Check tunnel](#check-tunnel)

# InterLink Kubernetes Plugin

Launch InterLink Kubernetes Plugin as follows:
```sh
python -m uvicorn main:app --reload --host=0.0.0.0 --port=30400
```

# TCP-Tunnel Helm Chart

Microservices offloading leverages a TCP Tunnel to forward traffic from the *local* cluster to the *remote* cluster where pods will be offloaded.
As part of this plugin's development, folder src/infr/charts includes a Helm chart to install a TCP Tunnel for secure connections between a pair of Gateway and Bastion hosts.

## Install

Generate an SSH key pair:
```sh
ssh-keygen -t rsa -b 4096 -C "interlink-gateway-key" -f ./private/ssh/id_rsa
# Base64 encoding of private key:
base64 --wrap 0 ./private/ssh/id_rsa
```

Helm chart includes two subcharts to be installed separately:
- chart `gateway` to be installed on the *local* cluster
- `bastion` chart to be installed on the *remote* cluster

### Install Gateway

Install Gateway on the *local* cluster.

**Example.**

Install release `msoff` (microservice offloading):
```sh
helm install msoff ./infr/charts/tcp-tunnel/charts/gateway \
    --namespace myservice --create-namespace \
    --set ssh.publicKey="$(cat ./private/ssh/id_rsa.pub)" \
    --dry-run --debug
```

> **Note:** option `--dry-run --debug` returns the generated template without submitting it.

The command above deploys a Gateway pod that listens for SSH connections on public port 30222 (through a NodePort); the Bastion pod will connect through that port to create a Reverse SSH tunnel.

You can specify `tunnel.service` parameters to additionally expose a public port (through a NodePort) that will be used later as the source of the TCP traffic to be forwarded through the Reverse SSH tunnel:
```sh
helm install msoff ./infr/charts/tcp-tunnel/charts/gateway \
    --namespace myservice --create-namespace \
    --set ssh.publicKey="$(cat ./private/ssh/id_rsa.pub)" \
    --set tunnel.service.sourcePort=8181 \
    --set tunnel.service.sourceNodePort=30181 \
    --dry-run --debug
```

### Install Bastion

Install Bastion on the *remote* cluster.

**Example.**

Install release `msoff` (microservice offloading):
```sh
GATEWAY_HOST=131.154.98.96
SERVICE_HOST=mlaas-inference-service-hep-predictor-00001.mlaas.svc.cluster.local
helm install msoff ./infr/charts/tcp-tunnel/charts/bastion \
    --namespace myservice --create-namespace \
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
