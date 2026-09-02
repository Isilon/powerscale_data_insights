# Deployment

PowerScale Data Insights can be deployed as standalone binaries, Docker
containers, or as a full evaluation stack via Docker Compose.

## Binary Deployment

### Install

Download pre-built binaries from the
[GitHub Releases](https://github.com/Isilon/powerscale_data_insights/releases)
page, or build and install from source:

```bash
make build
sudo make install
# Installs binaries to /usr/local/bin and example configs to
# /etc/powerscale-data-insights/. Starter configs are written only if
# they do not already exist.
```

To install to a different prefix (e.g. `/opt/pdi`):

```bash
sudo make install PREFIX=/opt/pdi
```

For package builds, set `DESTDIR`:

```bash
make install DESTDIR=/tmp/pkg-root
```

### Configuration

The installer copies starter configs to `/etc/powerscale-data-insights/`.
Edit them with your cluster and InfluxDB details:

```bash
sudo $EDITOR /etc/powerscale-data-insights/gostats.toml
sudo $EDITOR /etc/powerscale-data-insights/goppstats.toml
sudo $EDITOR /etc/powerscale-data-insights/goquotas.toml
```

See [Configuration Reference](configuration.md).

### systemd Service Files

Service files are included in the `systemd/` directory and can be installed with:

```bash
sudo make install-systemd
```

This copies the gostats, goppstats, and goquotas units
to `/etc/systemd/system/` and prints the remaining setup steps. If you need to
install to a different location:

```bash
sudo make install-systemd SYSTEMDDIR=/usr/lib/systemd/system
```

Enable and start:

```bash
# Create a dedicated service user
sudo useradd -r -s /usr/sbin/nologin pdi
sudo mkdir -p /var/log/powerscale-data-insights
sudo chown pdi:pdi /var/log/powerscale-data-insights

# If using $env: for passwords, add them to an environment file
sudo tee /etc/powerscale-data-insights/env > /dev/null <<'EOF'
CLUSTER_PASS=your-password-here
EOF
sudo chmod 600 /etc/powerscale-data-insights/env

# Add to each service file under [Service]:
#   EnvironmentFile=/etc/powerscale-data-insights/env

sudo systemctl daemon-reload
sudo systemctl enable --now pdi-gostats pdi-goppstats pdi-goquotas
```

Manage:

```bash
sudo systemctl status pdi-gostats
sudo systemctl restart pdi-gostats
sudo systemctl reload pdi-gostats     # sends SIGHUP, reloads config
sudo journalctl -u pdi-gostats -f     # follow logs
```

## Docker (Standalone Containers)

### Build

From the project root:

```bash
docker build -f docker/Dockerfile.gostats -t pdi-gostats .
docker build -f docker/Dockerfile.goppstats -t pdi-goppstats .
docker build -f docker/Dockerfile.goquotas -t pdi-goquotas .
```

Images are ~23MB (Alpine-based, statically linked binary).

### Run

Mount your config file into the container:

```bash
docker run -d --name gostats \
  --restart unless-stopped \
  -v /path/to/gostats.toml:/etc/gostats/idic.toml:ro \
  pdi-gostats

docker run -d --name goppstats \
  --restart unless-stopped \
  -v /path/to/goppstats.toml:/etc/goppstats/goppstats.toml:ro \
  pdi-goppstats

docker run -d --name goquotas \
  --restart unless-stopped \
  -v /path/to/goquotas.toml:/etc/goquotas/goquotas.toml:ro \
  pdi-goquotas
```

In your config file, set `log_to_stdout = true` so logs are visible via
`docker logs`. Set the InfluxDB host to whatever is reachable from the
container (e.g., host IP or Docker network alias).

### Pre-built Images

Pre-built images are published to GitHub Container Registry on each release:

```bash
docker pull ghcr.io/isilon/pdi-gostats:latest
docker pull ghcr.io/isilon/pdi-goppstats:latest
docker pull ghcr.io/isilon/pdi-goquotas:latest
```

## Docker Compose (Evaluation Stack)

The Docker Compose stack brings up InfluxDB, Grafana, and all collectors
in one command. Dashboards and the InfluxDB datasource are provisioned
automatically.

### Setup

```bash
cd docker/
cp gostats.example.toml gostats.toml
cp goppstats.example.toml goppstats.toml
cp goquotas.example.toml goquotas.toml
```

Edit the files — set your cluster hostname, username, and password in the
`[[cluster]]` section. The InfluxDB host is already set to `influxdb` (the
Compose service name) and logging is set to stdout.

### Start

```bash
docker compose up -d
```

### Access

- **Grafana:** [http://localhost:3000](http://localhost:3000) (admin / admin)
- **InfluxDB:** [http://localhost:8086](http://localhost:8086)

Dashboards appear under the **PowerScale** folder in Grafana.

### Stop

```bash
docker compose down       # stop containers, keep data
docker compose down -v    # stop containers and delete all data
```

### Monitoring Multiple Clusters

Add additional `[[cluster]]` sections to `gostats.toml`, `goppstats.toml`,
and `goquotas.toml`:

```toml
[[cluster]]
hostname = "cluster-a.example.com"
username = "statsuser"
password = "password-a"
verify-ssl = false

[[cluster]]
hostname = "cluster-b.example.com"
username = "statsuser"
password = "password-b"
verify-ssl = false
```

Restart the collectors: `docker compose restart gostats goppstats goquotas`

## Kubernetes

Container images can be deployed to Kubernetes using standard patterns.
A Helm chart is on the backlog; in the meantime, here is guidance for
manual deployment.

### Key Considerations

- Mount config files via ConfigMaps or Secrets (use Secrets for configs
  containing passwords, or use `$env:` substitution with Secret-sourced
  environment variables).
- Set `log_to_stdout = true` and `logfile_format = "json"` for structured
  log aggregation.
- Set the InfluxDB host to the in-cluster service name.
- The collectors are stateless — they can be restarted freely.
- Use `Deployment` with `replicas: 1` (running multiple replicas of the
  same collector against the same cluster would produce duplicate data).

### Example Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: pdi-gostats
spec:
  replicas: 1
  selector:
    matchLabels:
      app: pdi-gostats
  template:
    metadata:
      labels:
        app: pdi-gostats
    spec:
      containers:
        - name: gostats
          image: ghcr.io/isilon/pdi-gostats:latest
          args: ["-config-file", "/etc/gostats/gostats.toml"]
          env:
            - name: CLUSTER_PASS
              valueFrom:
                secretKeyRef:
                  name: pdi-credentials
                  key: cluster-password
          volumeMounts:
            - name: config
              mountPath: /etc/gostats
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: pdi-gostats-config
```

## Cross-Platform Releases

GoReleaser builds binaries for:

| OS | Architectures |
|----|---------------|
| Linux | amd64, arm64 |
| macOS | amd64, arm64 |
| Windows | amd64, arm64 |

Download from the
[GitHub Releases](https://github.com/Isilon/powerscale_data_insights/releases)
page. Each release includes checksums for verification.
