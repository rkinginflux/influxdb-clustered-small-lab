# Install InfluxDB Clustered in a small Kubernetes lab

## What this chapter builds

This is the database installation, after SeaweedFS is ready. First we give
Kubernetes permission to download your licensed software. Then we create
PostgreSQL for metadata, tell Clustered where its metadata and object storage
live, and ask its operator to start the distributed components. Finally we
write two small test measurements and query them back.

The operator is a controller that performs installation work for you; Helm
finishing does not necessarily mean the database is ready yet. That is why
this chapter has separate workload, authentication and query checkpoints.
If product names or Kubernetes terms are unfamiliar, read
[Start here](start-here.md) before running these commands.

## Scope and evidence

These are **new, sanitized starter examples**, checked offline with YAML parsing,
Helm lint/template, Python helper tests and the installed influxctl 2.12.2 help.
They were **not used to provision a fresh cluster**. An existing reference lab
successfully ran chart 0.1.28/package 20261016-2070790 with PostgreSQL 14,
authenticated TLS writes and SQL readback. That historical success is not proof
that every generic example here has been exercised live. In particular, the
un-pinned placement, default GC settings and localhost gateway differ from that
lab. Helm rendering validates the chart, not the remotely fetched OCI package's
full schema or runtime behavior. The acceptance gates below remain yours to run.

Read [prerequisites and security boundaries](prerequisites.md). Kubernetes and
S3 must already work. This is a guide plus small credential/profile helpers, not
an unattended installer. Commands marked **changes cluster state** are for an
intentional new lab install; do not run them against an existing database just
to see whether the instructions work. No real worker names, addresses, keys,
license material or database tokens belong in public examples.

All commands assume the repository root, one **Bash** shell and a dedicated
lab cluster. Stop on failure rather than skipping a gate.

## 1. Select your cluster and local workspace

Local setup and read-only discovery:

```bash
set -euo pipefail
umask 077
# Run from your checkout of influxdb-clustered-small-lab.
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
export NS=influxdb3-clustered
export RELEASE=influxdb3-clustered
export LOCAL="$PWD/examples/clustered/.local"
mkdir -p "$LOCAL"
chmod 700 "$LOCAL"
# Enter YOUR expected context before continuing.
read -r -p 'Expected Kubernetes context: ' EXPECTED_CONTEXT
test -n "$EXPECTED_CONTEXT"
test "$(kubectl config current-context)" = "$EXPECTED_CONTEXT"
kubectl get nodes
kubectl get storageclass local-path
kubectl -n s3 get pods
kubectl -n s3 get service seaweedfs-s3
helm list -A
kubectl get ingressclass
# Stop if any controller would serve the example class lab-gateway-unused.
for tool in kubectl helm python3 curl openssl tar sha256sum; do command -v "$tool"; done
python3 -m venv "$LOCAL/venv"
"$LOCAL/venv/bin/python" -m pip install 'PyYAML==6.0.3'
```

If this checkout is in Git, `git check-ignore examples/clustered/.local/probe`
must report that path. All private inputs and downloaded artifacts below stay
under this ignored directory. Never paste credentials into tracked files.

Inspect existing Helm releases first. If a global kubit operator already exists,
stop and review ownership/`skipOperator` using the official chart documentation;
do not adopt or overwrite another installation with these commands.

## 2. Retrieve the official chart and verify metadata

Local/network only; no Kubernetes writes. Use the explicit chart source, not a
copy shipped in this repository:

```bash
helm pull influxdb3-clustered --repo https://helm.influxdata.com \
  --version 0.1.28 --destination "$LOCAL"
printf '%s  %s\n' \
  860c355aed2e00642a1ba6471fc0ba71d4ea1f09701f518f9380570606aa6b58 \
  "$LOCAL/influxdb3-clustered-0.1.28.tgz" | sha256sum --check -
helm show chart "$LOCAL/influxdb3-clustered-0.1.28.tgz"
mkdir -p "$LOCAL/charts"
tar -xzf "$LOCAL/influxdb3-clustered-0.1.28.tgz" -C "$LOCAL/charts"
export CHART="$LOCAL/charts/influxdb3-clustered"
"$LOCAL/venv/bin/python" - <<'PY'
import os
from pathlib import Path
import yaml
m = yaml.safe_load((Path(os.environ['CHART']) / 'Chart.yaml').read_text())
assert m['name'] == 'influxdb3-clustered'
assert m['version'] == '0.1.28'
assert str(m['appVersion']) == '20261016-2070790'
print('Official chart metadata matches the pinned pair')
PY
```

The archive URL in the official Helm index is
`https://github.com/influxdata/helm-charts/releases/download/influxdb3-clustered-0.1.28/influxdb3-clustered-0.1.28.tgz`.
The SHA-256 above was read from that index. A checksum ties the archive to the
published index; it is not independent publisher signature verification. Stop
and investigate a mismatch, rather than replacing the expected checksum blindly.

`Chart.yaml` points to `https://github.com/influxdata/influxdb` as a source;
that metadata is **not** the licensed OCI package or registry credential source.
The chart AppInstance template fetches
`us-docker.pkg.dev/influxdb2-artifacts/clustered/influxdb:20261016-2070790`.
Helm does not render the actual IOx deployments locally. Authorized package/image
access is still required from the cluster. No package export is bundled here.

## 3. Check compatible placement and customize values

On **each candidate worker**, inspect its exposed CPU flags (for example,
`lscpu` or `/proc/cpuinfo` through your approved node access). Verify AVX2 and
compatibility with the supplied image; do not infer compatibility from a name.
Then explicitly label only those workers. **Changes node metadata:**

```bash
read -r -p 'Space-separated verified compatible worker names (at least 3): ' WORKERS
read -r -a COMPATIBLE_NODES <<< "$WORKERS"
test "${#COMPATIBLE_NODES[@]}" -ge 3
# Verify the list contains DISTINCT Ready, schedulable workers, without blocking taints.
kubectl get nodes "${COMPATIBLE_NODES[@]}" -o json > "$LOCAL/eligible-nodes.json"
python3 - "$LOCAL/eligible-nodes.json" <<'PY'
import json, sys
from pathlib import Path
nodes = json.loads(Path(sys.argv[1]).read_text())['items']
assert len({n['metadata']['name'] for n in nodes}) >= 3, 'Need three DISTINCT nodes'
for n in nodes:
    assert not n['spec'].get('unschedulable', False), 'A selected node is cordoned'
    assert any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions'])
    assert not any(t.get('effect') in ('NoSchedule', 'NoExecute') for t in n['spec'].get('taints', [])), 'Review blocking taints before proceeding'
print('Three or more distinct Ready, schedulable candidate nodes; verify CPUs separately')
PY
kubectl label nodes "${COMPATIBLE_NODES[@]}" lab.example.com/influxdb-avx2=true --overwrite
kubectl get nodes -l lab.example.com/influxdb-avx2=true
cp examples/clustered/values.yaml "$LOCAL/values.yaml"
```

Review `$LOCAL/values.yaml`: bucket/endpoint/region, StorageClass, hostname,
resources and placement. The label key `lab.example.com/influxdb-avx2` is an
example convention you control; changing it requires changing every matching
selector. All six IOx roles are constrained, including GC. Supporting services
need not use AVX2. The node list prompt does not independently inspect CPUs.

**Preserve three catalog replicas on three distinct eligible nodes.** The package
has three catalog peers and placement constraints; lowering replicas or pinning
all catalogs to one hostname is not a supported small-lab shortcut. The chart
uses the unusual `resources.<role>.requests.replicas` schema, not a top-level
`replicaCount`. One ingester is a deliberate non-HA lab reduction.

The generic admin identity is `admin@example.invalid`, not a real user. The
local bootstrap-admin path avoids configuring an external identity provider for
this disposable lab; do not use the localhost JWKS placeholder as production SSO.
Leave `featureFlags: []`; Grafana is a separate optional topic. Review default
GC/backup resource needs rather than assuming the five-role subtotal is complete.

## 4. Supply registry access, S3 identity and license privately

Place the provider-issued Docker credential configuration at
`$LOCAL/registry-config.json` and the provider-issued license bundle at
`$LOCAL/license.yaml`, using your approved secure transfer/editor. Do not use
example passwords or another person's credentials. Confirm the registry config
has the required registry hosts. Do not print its content.

**Changes cluster state:**

```bash
kubectl create namespace "$NS"
kubectl create namespace kubit
# The chart owns the kubit Namespace; pre-creation allows its pull Secret to exist.
kubectl label namespace kubit app.kubernetes.io/managed-by=Helm
kubectl annotate namespace kubit \
  meta.helm.sh/release-name="$RELEASE" meta.helm.sh/release-namespace="$NS"
chmod 600 "$LOCAL/registry-config.json" "$LOCAL/license.yaml"
for namespace in "$NS" kubit; do
  kubectl -n "$namespace" create secret generic gar-docker-secret \
    --type=kubernetes.io/dockerconfigjson \
    --from-file=.dockerconfigjson="$LOCAL/registry-config.json"
done
```

These create commands deliberately stop on existing resources; do not suppress
those errors and silently reuse an unknown installation. Registry Secrets are
namespace-scoped: both the operator and application namespaces need access.

Obtain the **resolved** S3 access/secret key for the existing bucket identity;
prefer bucket-scoped read/write/delete permissions, not cluster-wide admin keys.
If a SeaweedFS config uses `${ENV_VAR}` placeholders, resolve the backing secret
through your authorized process, not by using the literal placeholder as a key.
Read-only/list-only credentials are insufficient. Save the two raw values in
private files without adding trailing newlines, then create Secret references:

```bash
read -r -s -p 'S3 access key: ' S3_ACCESS; printf '\n'
printf '%s' "$S3_ACCESS" > "$LOCAL/s3-access-key"; unset S3_ACCESS
read -r -s -p 'S3 secret key: ' S3_SECRET; printf '\n'
printf '%s' "$S3_SECRET" > "$LOCAL/s3-secret-key"; unset S3_SECRET
kubectl -n "$NS" create secret generic influxdb3-object-store-access-key \
  --from-file=accessKey="$LOCAL/s3-access-key"
kubectl -n "$NS" create secret generic influxdb3-object-store-secret-key \
  --from-file=secretKey="$LOCAL/s3-secret-key"
```

Install official license CRDs before License objects. A supplied bundle may
contain both. The following splits the user-supplied bundle locally without
printing its material; **it does not supply or fabricate a license**:

```bash
"$LOCAL/venv/bin/python" - <<'PY'
import os
from pathlib import Path
import yaml
p = Path(os.environ['LOCAL'])
objects = [x for x in yaml.safe_load_all((p/'license.yaml').read_text()) if x]
crds = [x for x in objects if x['kind'] == 'CustomResourceDefinition']
rest = [x for x in objects if x['kind'] != 'CustomResourceDefinition']
assert rest, 'Expected a provider-issued License resource'
for name, values in [('license-crds.yaml', crds), ('license-resources.yaml', rest)]:
    (p/name).write_text(yaml.safe_dump_all(values))
    (p/name).chmod(0o600)
PY
if [ -s "$LOCAL/license-crds.yaml" ]; then
  kubectl apply -f "$LOCAL/license-crds.yaml"
fi
kubectl wait --for=condition=Established crd/licenses.influxdata.io --timeout=60s
kubectl -n "$NS" apply -f "$LOCAL/license-resources.yaml"
```

If the provider's license file contains no CRD and the CRD is absent, stop and
obtain/install the official license CRD from the provider's instructions. Do not
invent a CRD. Review any explicit namespaces in the supplied bundle privately;
`-n` does not rewrite an explicitly different namespace. A license controller
created by the package later materializes `iox-license`.

## 5. Generate NEW PostgreSQL authentication and install PostgreSQL

The helper writes a cryptographically generated password and URL-encoded DSNs
into an ignored mode-0600 JSON file. It refuses to overwrite it. The public
manifest contains **only Secret references**, never a password.

```bash
python3 examples/postgres/generate-auth.py
kubectl -n "$NS" apply -f "$LOCAL/postgres-secrets.json"
kubectl apply --dry-run=server -f examples/postgres/postgres.yaml
kubectl apply -f examples/postgres/postgres.yaml
kubectl -n "$NS" rollout status statefulset/influxdb3-postgres --timeout=180s
# Actual authenticated SQL; readiness alone is not an authentication test.
kubectl -n "$NS" exec influxdb3-postgres-0 -- sh -ec \
  'PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT 1"'
kubectl -n "$NS" get pvc
```

The probe is `sh -ec 'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'`.
Expansion occurs **inside the container**, including Secret-backed env values.
A bare `pg_isready` run as OS root can generate `role "root" does not exist`
noise even while returning ready. Never regenerate auth against an initialized
PVC: PostgreSQL initialization env variables do not rotate an existing SQL role.

## 6. Render, inspect and install Clustered

Local validation, then **changes cluster state**:

```bash
helm lint "$CHART" -f "$LOCAL/values.yaml"
helm template "$RELEASE" "$CHART" --namespace "$NS" \
  -f "$LOCAL/values.yaml" > "$LOCAL/chart-rendered.yaml"
# Review rendered RBAC and AppInstance privately before installing.
helm upgrade --install "$RELEASE" "$CHART" --namespace "$NS" \
  -f "$LOCAL/values.yaml" --wait --timeout 5m
kubectl -n kubit rollout status deployment/kubit --timeout=180s
kubectl -n "$NS" get appinstance "$RELEASE"
```

A successful Helm wait can mean only that kubit is ready. The operator fetches
and renders the OCI package asynchronously. Wait for the expected application
controller to **exist** before waiting on all rollouts:

```bash
found=false
for attempt in {1..180}; do
  if kubectl -n "$NS" get statefulset iox-shared-catalog >/dev/null 2>&1; then
    found=true; break
  fi
  sleep 5
done
$found
kubectl -n "$NS" rollout status statefulset --timeout=12m
kubectl -n "$NS" rollout status deployment --timeout=12m
kubectl -n "$NS" get deploy,statefulset,pods,pvc
kubectl -n "$NS" get secret iox-license -o name
kubectl -n "$NS" get pods -l app=iox -o wide
kubectl -n "$NS" get service core global-router iox-shared-querier
```

**Gate:** catalog StatefulSet desired/ready `3/3`, its three pods placed on three
compatible distinct nodes, all expected application workloads ready, PVCs Bound,
license Secret present, no crash loops or pending placement. Inspect pod labels
if `app=iox` does not enumerate everything in a future package. Do not proceed
with just one catalog or a green Helm release. Review actual router replication
configuration before making any claim about replicated writes.

## 7. Add the local TLS gateway

The lab gateway deliberately routes actual Clustered Services:

| Client protocol/path | Upstream |
|---|---|
| Management HTTP `/api/v0` | `core:9091` |
| Management gRPC (default route) | `core:8091` |
| Line protocol `/write`, `/api/v2/write` | `global-router:8080` |
| InfluxQL `/query`, `/ping` | `iox-shared-querier:8081` |
| Arrow Flight + gRPC reflection | `iox-shared-querier:8082` |

There is no universal standalone `:8181` server here. SQL via influxctl uses
Flight/gRPC with HTTP/2; testing an HTTP ping alone does not test SQL routing.
The health endpoint below checks only NGINX, not database health. This gateway is
a local customization, not a production ingress recommendation. The values assign
both package Ingress routes to the intentionally unhandled class
`lab-gateway-unused`; before installing, check `kubectl get ingressclass` and
confirm no controller serves that class (including controllers with unusual
watch-all behavior). Do not let an existing default ingress expose these routes.
The separate ClusterIP gateway is the intended entry point.

Create a self-signed localhost certificate and reference it through a Secret.
**Changes cluster state:**

```bash
test ! -e "$LOCAL/tls.key"
openssl req -x509 -newkey rsa:2048 -nodes -days 30 \
  -keyout "$LOCAL/tls.key" -out "$LOCAL/tls.crt" \
  -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1'
chmod 600 "$LOCAL/tls.key" "$LOCAL/tls.crt"
kubectl -n "$NS" create secret tls clustered-gateway-tls \
  --cert="$LOCAL/tls.crt" --key="$LOCAL/tls.key"
kubectl apply --dry-run=server -f examples/gateway/gateway.yaml
kubectl apply -f examples/gateway/gateway.yaml
kubectl -n "$NS" rollout status deployment/clustered-gateway --timeout=180s
```

In a **second terminal**, select the same kubeconfig and keep this running:

```bash
kubectl -n influxdb3-clustered port-forward --address 127.0.0.1 \
  service/clustered-gateway 8443:443
```

Back in the original shell:

```bash
curl --fail --silent --show-error --cacert "$LOCAL/tls.crt" https://localhost:8443/healthz
```

The generated CLI profiles use `localhost:8443` and explicitly trust that
certificate. To use another hostname/exposure later, generate matching SANs,
review firewall/TLS policy and update profiles. A self-signed private key stays
private. Stop port-forward with Ctrl-C when finished. Gateway access logging is
disabled to avoid request/query-string disclosure; don't add Authorization
headers to access logs. ConfigMap or TLS Secret changes require an intentional
gateway reload/restart, followed by verification.

## 8. Download influxctl and build the management profile

Local download, read of the bootstrap Secret, local private files:

```bash
curl --fail --location --silent --show-error \
  https://dl.influxdata.com/influxctl/releases/influxctl-v2.12.2-linux-x86_64.tar.gz \
  --output "$LOCAL/influxctl-v2.12.2-linux-x86_64.tar.gz"
# Inspect the official archive; extract only the executable, not upstream configs.
tar -tzf "$LOCAL/influxctl-v2.12.2-linux-x86_64.tar.gz"
tar -xzf "$LOCAL/influxctl-v2.12.2-linux-x86_64.tar.gz" -C "$LOCAL" influxctl
chmod 755 "$LOCAL/influxctl"
"$LOCAL/influxctl" version
# Never emit the token to a terminal or shared log.
kubectl -n "$NS" get secret admin-token -o jsonpath='{.data.token}' \
  | base64 --decode > "$LOCAL/admin-token.json"
chmod 600 "$LOCAL/admin-token.json"
python3 examples/clustered/profiles.py management
"$LOCAL/influxctl" --config "$LOCAL/management.toml" database list
```

This archive is Linux x86-64 only. Use the corresponding official artifact for
another client platform and verify its version. Follow the publisher's available
checksum/signature verification guidance; no invented CLI checksum is supplied.

Management/bootstrap tokens authorize database and token administration, not a
substitute for the database-scoped `token` field used by data write/query calls.
Keep debug/trace logging off when handling credentials. For production, configure
a supported identity provider rather than this bootstrap bypass.

## 9. Create a database and scoped data token, then verify write + SQL

**Changes database state:** use a new database name for this fixture. If
`lab_smoke` already exists, inspect it instead of deleting it or ignoring errors.

```bash
"$LOCAL/influxctl" --config "$LOCAL/management.toml" database create lab_smoke
"$LOCAL/influxctl" --config "$LOCAL/management.toml" token create \
  --read-database lab_smoke --write-database lab_smoke --format json \
  'Disposable lab smoke test' > "$LOCAL/data-token.json"
chmod 600 "$LOCAL/data-token.json"
python3 examples/clustered/profiles.py data
```

The database token is returned only at creation; save it privately. Token
propagation is asynchronous. The reference lab observed a roughly ten-second
authz refresh; do not assume immediate validity or mint repeated tokens.
The pinned CLI initializes management authentication even for these data
commands, so the generated data profile retains its private bootstrap
`auth.token.token_file` reference as well as the database-scoped `token`.
Removing that auth stanza failed a real read-only check against the reference
lab. This is CLI initialization behavior, not permission to distribute the
bootstrap token to collectors or Grafana: those use only their scoped data tokens.
The following retries only initial `invalid token` failures, bounded to 60 seconds:

```bash
written=false
for attempt in {1..13}; do
  if "$LOCAL/influxctl" --config "$LOCAL/data.toml" write --database lab_smoke \
    examples/clustered/smoke.lp > "$LOCAL/write.out" 2> "$LOCAL/write.err"; then
    written=true; break
  fi
  if ! python3 - "$LOCAL/write.err" <<'PY'
import sys
from pathlib import Path
sys.exit(0 if 'invalid token' in Path(sys.argv[1]).read_text().lower() else 1)
PY
  then
    printf 'Write failed for a different reason; inspect private write.err locally.\n' >&2
    exit 1
  fi
  if [ "$attempt" -lt 13 ]; then sleep 5; fi
done
$written
"$LOCAL/influxctl" --config "$LOCAL/data.toml" query --database lab_smoke \
  'SELECT * FROM lab_smoke ORDER BY time, room'
"$LOCAL/influxctl" --config "$LOCAL/data.toml" query --database lab_smoke --format json \
  'SELECT COUNT(*) AS row_count FROM lab_smoke' > "$LOCAL/query.json"
python3 - "$LOCAL/query.json" <<'PY'
import json, sys
from pathlib import Path
rows = json.loads(Path(sys.argv[1]).read_text())
assert isinstance(rows, list) and len(rows) == 1 and rows[0]['row_count'] == 2
print('PASS: authenticated write and Flight SQL returned the expected two rows')
PY
```

The two points use fixed timestamps and tags: rewriting them is logically
idempotent, not two additional rows each time. This does **not** prove disk/object
persistence, backup safety, node-loss tolerance or production performance.

## 10. Persistence verification and later operations

To demonstrate storage separately, use approved tooling to inspect the shipped
IOx image's `debug --help` before using a version-specific persistence command.
Write synthetic fixtures only; verify signed S3 object I/O and persisted Parquet
objects in `lab`, then repeat the SQL count. Do not use PVC deletion or forced
Ingester termination as a persistence test. Persistence was checked in the
reference lab, but no automatic generic persistence test is claimed here.

For upgrades, back up catalog/object data with a tested restore plan, inspect
new chart/package schema and checkpoint releases, render/diff deliberately, then
wait for the **application** again and repeat authenticated write/query checks.
Do not bundle downloaded charts/binaries or generated `.local` content into a
public commit. Do not share full Helm values, Secret YAML, private profiles,
DSNs, token-create output or unreviewed logs.

See [troubleshooting](troubleshooting.md) before intervention. There is
intentionally no destructive cleanup script: deleting a namespace, PVC or bucket
can destroy the only copy of this lab's data.

## Reproduce the offline checks

After retrieving the official chart in step 2:

```bash
PYTHONDONTWRITEBYTECODE=1 "$LOCAL/venv/bin/python" \
  examples/clustered/validate.py --chart "$CHART"
```

This performs Helm lint/template, checks the seven owned example YAML documents,
checks catalog count and all IOx selectors, exercises shell expansion using a
harmless local probe stand-in, and tests credential/profile generation, file
permissions and overwrite refusal in a temporary ignored sandbox. Profile tests
use an explicitly synthetic token fixture, never a fabricated live API result.
It also checks Service selectors, computes the resource subtotals and syntax-checks
the Bash blocks in these three guides. Temporary test credentials are deleted.
It does **not** contact Kubernetes, validate the full OCI package schema, run
NGINX, test real authentication or claim a fresh install. Those require the
installation acceptance gates above.

## Sources

- [Official deployment guide](https://docs.influxdata.com/influxdb3/clustered/install/set-up-cluster/deploy/)
- [Official chart repository](https://github.com/influxdata/helm-charts/tree/master/charts/influxdb3-clustered)
- [Official test-cluster/bootstrap token workflow](https://docs.influxdata.com/influxdb3/clustered/install/set-up-cluster/test-cluster/)
- [influxctl profile and TLS schema](https://docs.influxdata.com/influxdb3/clustered/reference/cli/influxctl/)
- [Management versus database tokens](https://docs.influxdata.com/influxdb3/clustered/admin/tokens/)
