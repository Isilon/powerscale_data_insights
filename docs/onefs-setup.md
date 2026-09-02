# OneFS Setup

How to create a dedicated user on your PowerScale cluster for statistics
collection.

## Required Privileges

| Privilege | Required by | Purpose |
|-----------|-------------|---------|
| `ISI_PRIV_LOGIN_PAPI` (read-only) | all PAPI clients | Log in to the Platform API |
| `ISI_PRIV_STATISTICS` | gostats | Read cluster and node statistics via PAPI |
| `ISI_PRIV_PERFORMANCE` | goppstats, dashgen | Read Partitioned Performance datasets via PAPI |
| `ISI_PRIV_NFS` (read-only) | goppstats (optional) | Resolve NFS export IDs to export paths |
| `ISI_PRIV_QUOTA` / `ISI_PRIV_QUOTA_QUOTAMANAGEMENT` (read-only) | goquotas | Read live quota configuration and accounting values |

If you only plan to run gostats, you only need `ISI_PRIV_STATISTICS`.
If you also run goppstats, add `ISI_PRIV_PERFORMANCE`. The NFS privilege
is optional and only needed if you set `lookup_export_ids = true` in the
goppstats config.

To run goquotas, the cluster must have SmartQuotas available and the account
must have read access to quota management. Granular fields such as efficiency
ratio or filesystem-physical usage may require the corresponding quota
subprivileges on newer OneFS releases.

## Create a Role and User via the CLI

Connect to your cluster via SSH and run:

```bash
# Create a role with the required privileges
isi auth roles create StatsCollector \
  --description="PowerScale Data Insights statistics collection"

isi auth roles modify StatsCollector \
  --add-priv-read ISI_PRIV_LOGIN_PAPI \
  --add-priv-read ISI_PRIV_STATISTICS \
  --add-priv-read ISI_PRIV_PERFORMANCE

# Add quota read access when running goquotas
isi auth roles modify StatsCollector \
  --add-priv-read ISI_PRIV_QUOTA \
  --add-priv-read ISI_PRIV_QUOTA_QUOTAMANAGEMENT

# Optional: add NFS privilege for export path resolution
isi auth roles modify StatsCollector \
  --add-priv-read ISI_PRIV_NFS

# Create a local user
isi auth users create statsuser --enabled=true \
  --password="your-secure-password"

# Assign the role
isi auth roles modify StatsCollector --add-user=statsuser
```

## Create a Role and User via the Web UI

1. Log in to the OneFS web administration interface
2. Navigate to **Access > Membership & Roles > Roles**
3. Click **Create a Role**
   - Name: `StatsCollector`
   - Description: `PowerScale Data Insights statistics collection`
4. Add privileges:
   - `ISI_PRIV_LOGIN_PAPI` (read-only)
   - `ISI_PRIV_STATISTICS` (read/write)
   - `ISI_PRIV_PERFORMANCE` (read-only)
   - `ISI_PRIV_NFS` (read-only, optional)
   - `ISI_PRIV_QUOTA` and `ISI_PRIV_QUOTA_QUOTAMANAGEMENT` (read-only, for goquotas)
5. Navigate to **Access > Membership & Roles > Users**
6. Click **Create a User**
   - Username: `statsuser`
   - Set a password
   - Enable the account
7. Go back to the **StatsCollector** role and add `statsuser` as a member

## Verify Access

From the machine that will run the collectors, test PAPI access:

```bash
# Test statistics access (gostats)
curl -k -u statsuser:password \
  "https://your-cluster:8080/platform/3/statistics/current?key=cluster.health"

# Test PP access (goppstats)
curl -k -u statsuser:password \
  "https://your-cluster:8080/platform/10/performance/datasets"

# Test live directory quota access (goquotas)
curl -k -u statsuser:password \
  "https://your-cluster:8080/platform/8/quota/quotas?type=directory&limit=1"
```

A successful response returns JSON with the requested data. A 403 response
indicates missing privileges.

## Security Considerations

- Use a **dedicated user** for statistics collection — do not use `root`
  or an administrative account in production.
- Use the **minimum required privileges** (read-only where possible).
- Use `$env:VARNAME` syntax in config files to load passwords from
  environment variables instead of storing them in plain text:

  ```toml
  [[cluster]]
  hostname = "your-cluster.example.com"
  username = "statsuser"
  password = "$env:CLUSTER_PASS"
  ```

- If TLS certificates are properly configured on your cluster, set
  `verify-ssl = true` in the cluster config. Use `verify-ssl = false`
  only for self-signed certificates in non-production environments.

## Multiple Clusters

All collectors support monitoring multiple clusters from a single instance.
Add additional `[[cluster]]` sections to the config file:

```toml
[[cluster]]
hostname = "cluster-east.example.com"
username = "statsuser"
password = "$env:CLUSTER_EAST_PASS"
verify-ssl = true

[[cluster]]
hostname = "cluster-west.example.com"
username = "statsuser"
password = "$env:CLUSTER_WEST_PASS"
verify-ssl = true
```

Each cluster runs in its own goroutine with independent authentication and
retry logic. Create the same role and user on each cluster.
