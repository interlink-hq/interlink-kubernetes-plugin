
# Index

- [Index](#index)
- [Install](#install)
- [Install Gateway](#install-gateway)
- [Install Bastion](#install-bastion)

A Helm chart to install a TCP Tunnel for secure connections between Gateway and Bastion hosts.

Chart `gateway` to be installed on the *local* cluster, while `bastion` chart to be installed on the *remote* cluster
where pods are offloaded.

# Install

Generate an SSH key pair if you don’t already have one:
```sh
ssh-keygen -t rsa -b 4096 -C "interlink-gateway-key" -f ./private/ssh/id_rsa
# Base64 encoding of private key:
base64 --wrap 0 ./private/ssh/id_rsa
```

# Install Gateway

Install Gateway on the *local* cluster.

**Example.**

Install release `ms`:
```sh
helm install ms ./tcp-tunnel/charts/gateway \
    --set ssh.publicKey=<content of id_rsa.pub> \
    --dry-run --debug
```

# Install Bastion

Install Bastion on the *remote* cluster.

**Example.**

Install release `ms`:
```sh
helm install ms ./tcp-tunnel/charts/bastion \
    --set ssh.privateKey=<base64 encoding of id_rsa> \
    --dry-run --debug
```
