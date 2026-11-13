# Prerequisites and boundaries

This is a small, disposable **InfluxDB Clustered** lab, not the standalone
InfluxDB 3 Core/Enterprise server. It is not production sizing or an HA design.
New to the product? Read [Start here](start-here.md) before this checklist.
The order is prerequisites, [SeaweedFS](seaweedfs.md), then
[the Clustered installation guide](clustered.md), then Grafana/Telegraf.
Do not execute deployment commands until the earlier checkpoint is complete.

## Supply these yourself

- A working Kubernetes cluster, CNI, DNS, and kubectl with appropriate permissions.
  Official Clustered docs specify kubectl 1.27 or newer; also obey Kubernetes
  client/server version-skew rules. Match your Kubernetes version to the current
  supported Clustered matrix rather than treating this as a universal minimum.
- **At least three distinct Ready, schedulable, compatible Linux x86-64 nodes**
  for the three catalog peers. Verify AVX2 in each node/VM's exposed CPU flags;
  workstation flags do not establish worker compatibility. Four compatible
  workers were available in the reference lab; one compatible node is NOT enough
  for this layout. Taints, free resources and volume topology must also permit
  placement. Do not remove control-plane taints blindly.
- Helm 3, Python 3.11+ (standard-library helpers use `tomllib` in validation),
  curl, OpenSSL, tar, sha256sum. Install PyYAML 6.0.3 into a virtualenv for the
  documented local validation and license-bundle splitting commands.
- A `local-path` StorageClass (or edit both examples to your class) with sufficient
  disk space and working dynamic provisioning. The example explicitly requests
  5Gi PostgreSQL, 5Gi ingester WAL and 1Gi monitoring storage, plus object-store
  capacity and package-default volumes. These are not total disk requirements.
- An existing authenticated S3-compatible server in namespace `s3`, Service
  `seaweedfs-s3`, port 8333, and existing bucket `lab`. Set these values to your
  own deployment if different. Follow this repository's [SeaweedFS chapter](seaweedfs.md)
  first if it is absent. Provisioning Kubernetes, CNI and local-path is outside
  this repository's scope. Clustered does not depend on a workstation
  S3 port-forward. Use signed PUT/GET/DELETE tests on a dedicated test object,
  not only bucket listing, before installation.
- Official **InfluxDB Clustered license and authorized registry access**, obtained
  from InfluxData. This repository supplies neither. Obtain the provider's valid
  Docker credential configuration and license manifest/bundle privately. A
  GitHub checkout or Helm chart download does not grant product access.
  The OCI package is
  `us-docker.pkg.dev/influxdb2-artifacts/clustered/influxdb:20261016-2070790`.
  The registry identity must be allowed to pull the package and its images.
- Network access from the cluster to official registries, dependencies and any
  license activation services required by your license. This is not an air-gap
  installation guide.

## Version contract

| Artifact | Reference version | Meaning |
|---|---|---|
| Official Helm chart | `0.1.28` | Installs kubit and an AppInstance, not all database workloads directly |
| Clustered OCI package | `20261016-2070790` | Explicit `image.tag`; chart `appVersion` matches |
| Kubit operator | `v0.0.22` | Chart default, explicitly retained |
| influxctl | `2.12.2` | Verify with `influxctl version`, not `--version` |
| PostgreSQL | `postgres:14-alpine` | Reference major/channel constraint, not an immutable digest |
| TLS gateway | `nginx:1.28-alpine` | Reference minor/channel constraint, not an immutable digest |

Package/chart/CLI pins are reproducibility constraints, not a recommendation to
skip security updates. Container tags can move; resolve and review image digests
for stronger reproducibility. Do not silently change package tags when a pull
fails. Review official checkpoint-release upgrade requirements before upgrades.
No upstream binaries, charts, package source or licensed software are bundled.

## Resource budget: subtotal, not a cluster minimum

The five explicitly sized IOx roles in `examples/clustered/values.yaml` request
**700m CPU and 3584Mi memory** in aggregate: one each ingester, querier,
compactor and router, plus **three** catalogs. Their aggregate limits are
**5 CPU and 10Gi memory**. These are small smoke-workload overrides, not capacity
promises. The garbage collector keeps package defaults.

Adding the example PostgreSQL (100m/256Mi requests; 1 CPU/1Gi limits), gateway
(25m/32Mi; 500m/128Mi) and chart kubit (10m/64Mi; 500m/128Mi) gives a **partial
subtotal of 835m CPU / 3936Mi requested and 7 CPU / 11520Mi limits**. These
numbers were computed from the files, multiplying by replicas. They exclude
GC, auth/management services, sidecars, monitoring, transient render/apply Jobs,
S3, CNI/DNS, system workloads and control-plane reservations. Inspect the
package-generated manifests and live allocated resources to budget the whole
cluster. Leave substantial memory/CPU/disk headroom; limits are not reservations.

## Security and durability boundaries

- Gateway TLS protects the client-to-gateway hop. Backend Clustered routes are
  cleartext inside the cluster. S3 explicitly uses HTTP (`allowHttp: "true"`)
  and PostgreSQL DSNs use `sslmode=disable`. Namespace separation is not traffic
  encryption or a NetworkPolicy. Do not expose these Services to untrusted LANs
  or the internet; use TLS and reviewed network controls for real environments.
- The default gateway is **ClusterIP**, accessed through a localhost-only
  `kubectl port-forward`. This avoids publishing a NodePort. A self-signed lab
  certificate is trusted explicitly using its CA/certificate file; do not solve
  trust failures with permanent `insecure`, `disable`, or `curl -k` settings.
- Kubit has broad cluster-level RBAC in the default chart. Use a dedicated test
  cluster, inspect those grants, and do not install competing global kubit
  operators. This guide does not harden that operator or provide tenant isolation.
- PostgreSQL is one pod and uses one generated lab owner identity for catalog
  and management DSNs. It is deliberately not a production least-privilege SQL
  role layout, a managed PostgreSQL service or a backup configuration.
- One ingester means no redundant ingester WAL copy. Three catalogs preserve
  their peer topology; they do not make singleton PostgreSQL/S3/WAL/gateway HA.
- Local PVs are node-bound. A node loss can make a volume unavailable; recreating
  a claim elsewhere is not data recovery. Preserve catalog, WAL and object-store
  data together, and test restore before claiming backup protection. Object
  versioning alone is not a coordinated database backup.
- `examples/clustered/.local/` is ignored. Keep it mode 0700 and credential files
  mode 0600; never use shell tracing when handling them. Git ignore rules do not
  remove already tracked secrets. Kubernetes Secrets are not encrypted merely
  because they use base64; protect RBAC, kubeconfig, backups and etcd encryption.

## Official references

- [Prerequisites](https://docs.influxdata.com/influxdb3/clustered/install/set-up-cluster/prerequisites/)
- [Helm configuration](https://docs.influxdata.com/influxdb3/clustered/install/set-up-cluster/configure-cluster/use-helm/)
- [Licensing](https://docs.influxdata.com/influxdb3/clustered/install/set-up-cluster/licensing/)
- [Upgrade guidance](https://docs.influxdata.com/influxdb3/clustered/admin/upgrade/)
