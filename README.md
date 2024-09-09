
InterLink plugin to offload the execution of a POD to a *remote* cluster.
The plugin supports the offloading of PODs that expose HTTP endpoints: a TCP Tunnel is setup to forward traffic from the *local* cluster to the *remote* cluster.

# Index

- [Index](#index)
- [Setup and Launch](#setup-and-launch)
- [TCP-Tunnel Helm Charts](#tcp-tunnel-helm-charts)

# Setup and Launch

File [config.sample.ini](src/private/config.sample.ini) provides plugin's configuration, rename file to *config.ini* and provide missing values, in particular:
- k8s.kubeconfig_path: path to the Kubeconfig yaml file to access the *remote* cluster
- tcp_tunnel.gateway_host: IP of the Gateway host where the Reverse SSH Tunnel will be created (See [tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md))
- tcp_tunnel.gateway_port: port to reach the Gateway's SSH daemon
- tcp_tunnel.gateway_ssh_private_key: the SSH private key

Launch InterLink Kubernetes Plugin as follows:
```sh
python -m uvicorn main:app --host=0.0.0.0 --port=30400
```

# TCP-Tunnel Helm Charts

This plugin leverages Helm chart [tcp-tunnel](src/infr/charts/tcp-tunnel) to install a TCP Tunnel for secure connections between a pair of Gateway and Bastion hosts.

See [tcp-tunnel/README.md](src/infr/charts/tcp-tunnel/README.md)
