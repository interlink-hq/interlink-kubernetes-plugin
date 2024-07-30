
# Index

- [Index](#index)
- [Install](#install)
  - [Install Gateway](#install-gateway)
  - [Install Bastion](#install-bastion)
  - [Check tunnel](#check-tunnel)

A Helm chart to install a TCP Tunnel for secure connections between Gateway and Bastion hosts.

Chart `gateway` to be installed on the *local* cluster, while `bastion` chart to be installed on the *remote* cluster
where pods are offloaded.

# Install

Generate an SSH key pair:
```sh
ssh-keygen -t rsa -b 4096 -C "interlink-gateway-key" -f ./private/ssh/id_rsa
# Base64 encoding of private key:
base64 --wrap 0 ./private/ssh/id_rsa
```

## Install Gateway

Install Gateway on the *local* cluster.

**Example.**

Install release `msoff` (microservice offloading):
```sh
helm install msoff ./tcp-tunnel/charts/gateway \
    --namespace myservice \
    --set ssh.publicKey="$(cat ../../src/private/ssh/id_rsa.pub)" \
    --dry-run --debug
```

> **Note:** option `--dry-run --debug` returns the generated template without submitting it.

The command above deploys a Gateway pod that listens for SSH connections on public port 30222 (through a NodePort); the Bastion pod will connect through that port to create a Reverse SSH tunnel.

You can specify `serviceTunnel` parameters to additionally expose a public port (through a NodePort) that will be used later as the source of the TCP traffic to be forwarded through the Reverse SSH tunnel:
```sh
helm install msoff ./tcp-tunnel/charts/gateway \
    --namespace myservice \
    --set ssh.publicKey="$(cat ../../src/private/ssh/id_rsa.pub)" \
    --set serviceTunnel.port=8181 \
    --set serviceTunnel.nodePort=30181 \
    --dry-run --debug
```

## Install Bastion

Install Bastion on the *remote* cluster.

**Example.**

Install release `msoff` (microservice offloading):
```sh
GATEWAY_HOST=192.135.24.221
SERVICE_HOST=mlaas-inference-service-hep-predictor-00001.mlaas.svc.cluster.local
helm install msoff ./tcp-tunnel/charts/bastion \
    --namespace myservice \
    --set gateway.host=${GATEWAY_HOST} \
    --set gateway.ssh.privateKey=$(base64 --wrap 0 ../../src/private/ssh/id_rsa ) \
    --set tunnel.serviceHost=${SERVICE_HOST} \
    --set tunnel.servicePort=80 \
    --set tunnel.gatewayPort=8181 \
    --dry-run --debug
```

## Check tunnel

Let's check whether traffic from ${GATEWAY_HOST}:30181 (*local* cluster) is forwarded to ${SERVICE_HOST}:80 in *remote* cluster.

```sh
curl --location http://${GATEWAY_HOST}:30181/v1/models/mlaas-inference-service-hep'
```
