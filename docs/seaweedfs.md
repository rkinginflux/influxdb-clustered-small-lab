# SeaweedFS S3 for a small, non-HA Kubernetes lab

## What this chapter builds

Clustered needs a place to keep persisted data files. Here, SeaweedFS supplies
that place on your own machines, with an S3-compatible API. You are not creating
an AWS cloud account. The `aws` CLI and Boto3 used below are clients that can
also connect to this local compatible service.

There are four pieces: the **master** tracks volume locations; the **volume
server** holds object bytes; the **filer** maintains file/directory metadata;
the **S3 gateway** translates S3 requests into that storage system. The first
three need persistent data storage. A bucket named `lab` holds Clustered's
objects; generated access/secret keys authorize clients to use it.

Your checkpoint is not just a green pod: it is a successful signed upload,
download with matching bytes, and deletion of a dedicated test object. Start
with internal/port-forward access, and add the optional NodePort only if you
want a stable endpoint on a trusted LAN. If these terms are new, see
[Start here](start-here.md).

## Scope and evidence

This guide targets **SeaweedFS Helm chart 4.48.0 / image 4.48**, release
`seaweedfs`, namespace `s3`. It uses separate master, volume, filer and S3
components, not the all-in-one server. Run commands from this repository's root.

**Validation is offline Helm lint/template validation against a locally available
vendored chart with `version: 4.48.0` and `appVersion: 4.48`. A fresh installation
of these examples has NOT been exercised.** A separate, existing deployment has
an established `seaweedfs-s3` Service at port 8333, optional NodePort 32333, and
in-cluster endpoint `http://seaweedfs-s3.s3.svc.cluster.local:8333`. Those existing
service facts are not proof that a fresh install, these resource limits, PVC
provisioning, or these newly generated credentials work. No live cluster was
queried or changed while preparing this guide.

The vendored chart is not distributed here. Obtain the pinned chart yourself;
version metadata alone does not guarantee byte-for-byte equivalence with a
locally modified chart. Re-run rendering checks against your downloaded copy.
References: [chart source](https://github.com/seaweedfs/seaweedfs/tree/master/k8s/charts/seaweedfs),
[S3 configuration](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API),
[local-path provisioner](https://github.com/rancher/local-path-provisioner).
The source link tracks upstream, not a frozen copy of the audited local chart.

## Prerequisites and boundaries

- A disposable/trusted Kubernetes lab, a correct kubeconfig/context, cluster DNS,
  and sufficient permissions to create a namespace, Secrets, workloads, Services,
  PVCs and the chart's RBAC resources. Helm 3, `kubectl`, Python 3 with `venv`,
  and network access to the chart repository, container registry and PyPI.
- A working dynamic StorageClass **named `local-path`**, schedulable nodes with
  free disk and enough memory/CPU for all four pods. This guide does not install
  a storage provisioner, remove control-plane taints, or change node labels.
- A fresh namespace/release name with no conflicting resources. Do not use this
  fresh-install values file to migrate an existing deployment's storage.
- Bash commands below; do not enable `set -x`, SDK debug logging, shell tracing,
  or CI command/environment dumps. Secrets never belong in Git, Helm values,
  command-line arguments, screenshots or public rendered manifests.
- AWS CLI v2 is optional for the CLI alternative. Boto3 is used by the verifier.

Read-only preflight (inspect locally; do not publish topology output):

```bash
kubectl config current-context
kubectl get storageclass local-path
kubectl get nodes
helm list -n s3
kubectl get services -A  # optional NodePort collision check
```

PVC requests below are 1Gi master, 2Gi filer metadata, 20Gi volume data/index.
The limits are starting points for tiny experiments, not tested capacity or
performance guarantees. Watch OOM/restarts and disk use. The master uses 1000MB
volume units and the single volume server allows seven volumes. Neither that
limit nor a PVC request is an application quota; local-path typically does not
enforce requested capacity as a hard filesystem limit.

## 1. Fetch the pinned chart and inspect/render it

```bash
helm repo add seaweedfs https://seaweedfs.github.io/seaweedfs/helm
helm repo update seaweedfs
# Keep third-party source outside this public checkout.
export CHART_WORKDIR="$(mktemp -d)"
helm pull seaweedfs/seaweedfs --version 4.48.0 --untar --untardir "$CHART_WORKDIR"
export SEAWEEDFS_CHART="$CHART_WORKDIR/seaweedfs"
helm show chart "$SEAWEEDFS_CHART"
helm lint "$SEAWEEDFS_CHART" -f examples/seaweedfs/values.yaml
helm template seaweedfs "$SEAWEEDFS_CHART" --namespace s3 \
  -f examples/seaweedfs/values.yaml > "$CHART_WORKDIR/rendered.yaml"
# Optional LAN exposure: validate this overlay too, before installing it.
helm template seaweedfs "$SEAWEEDFS_CHART" --namespace s3 \
  -f examples/seaweedfs/values.yaml \
  -f examples/seaweedfs/nodeport-values.yaml > "$CHART_WORKDIR/nodeport-rendered.yaml"
```

Rendering is not Kubernetes schema/admission validation or a storage/network test.
In the audited chart both variants render one master/filer/volume StatefulSet,
one S3 Deployment and three local-path ReadWriteOnce claim templates. No worker,
admin, credential-generation Secret hook, bucket hook or resize hook is rendered.
The S3 Service selects the S3 gateway and has only port 8333; the optional overlay
sets that port's NodePort to 32333. Metrics, Lance and Iceberg ports are disabled
to avoid exposing unrelated or automatically allocated NodePorts.

## 2. Generate credentials privately and create the configuration Secret

Use a **new directory outside the checkout**. The generator refuses an existing
directory and creates mode-0600 files in a mode-0700 directory. Keep a protected
backup; deleting these files does not rotate keys already installed in Kubernetes.
This identity has broad lab administration rights: do not reuse it outside this
lab or treat it as a least-privilege application account.

```bash
umask 077
export SEAWEEDFS_AUTH_DIR="$HOME/.config/seaweedfs-small-lab"
python3 examples/seaweedfs/generate_credentials.py "$SEAWEEDFS_AUTH_DIR"
# Inspect the selected context BEFORE these state-changing commands.
kubectl create namespace s3
kubectl -n s3 create secret generic seaweedfs-s3-config \
  --from-file=seaweedfs_s3_config="$SEAWEEDFS_AUTH_DIR/seaweedfs_s3_config"
# Read back metadata/key presence without exposing Secret data.
kubectl -n s3 get secret seaweedfs-s3-config \
  -o go-template='{{.metadata.name}}{{" key-present="}}{{if index .data "seaweedfs_s3_config"}}true{{else}}false{{end}}{{"\n"}}'
```

If namespace `s3` already exists, inspect ownership/use first and omit only its
creation after confirming this is a fresh release. Do not overwrite a preexisting
Secret or use `kubectl get secret -o yaml` for public troubleshooting.

### Exact chart 4.48.0 Secret contract

`examples/seaweedfs/values.yaml` sets `s3.enabled: true`, `s3.enableAuth: true`,
`s3.existingConfigSecret: seaweedfs-s3-config`, and `filer.s3.enabled: false`.
These are **standalone S3** settings; embedded filer S3 has separate keys.

- `existingConfigSecret` is the **name** of an already-created Secret in namespace
  `s3`, not a path, JSON string or a switch that creates a Secret.
- The required Secret **data key is exactly `seaweedfs_s3_config`**, not `config`,
  `config.json` or `s3.json`. `--from-file=key=filename` above sets it explicitly.
- `templates/s3/s3-deployment.yaml` mounts the entire Secret as a read-only volume
  at `/etc/sw`, without a key remapping. It starts `weed s3` with
  `-config=/etc/sw/seaweedfs_s3_config`. The key therefore becomes that filename.
- The file contains JSON with an `identities` array; each identity has `name`,
  `credentials` entries containing `accessKey` and `secretKey`, and `actions`.
  The generator builds this structure with secure random keys. There is no
  anonymous identity. `enableAuth` must remain true or the config flag/mount is
  omitted. A Secret name alone does not enable authentication.
- With this existing Secret, `templates/s3/s3-secret.yaml` does not render the
  generated credential Secret. No credentials are stored in public values or
  generated by Helm in this workflow.
- The gateway pod annotation `checksum/s3config` uses a Helm `lookup` of the
  existing Secret. Offline `helm template` sees an empty lookup; its checksum is
  not a prediction of an install/upgrade checksum. Updating the Secret alone is
  not a verified credential-rotation procedure: plan a gateway rollout and
  re-test signed requests. Never assume hot reload or credential preservation.

Kubernetes Secret base64 is not encryption. Limit RBAC, protect kubeconfig,
consider encryption at rest, and avoid exposing the unauthenticated master/filer/
volume interfaces. S3 authentication does not secure every internal SeaweedFS API.

## 3. Install (commands to run yourself; not exercised here)

Default, internal ClusterIP only:

```bash
helm install seaweedfs "$SEAWEEDFS_CHART" --namespace s3 \
  -f examples/seaweedfs/values.yaml --wait --timeout 10m
kubectl -n s3 rollout status statefulset/seaweedfs-master --timeout=300s
kubectl -n s3 rollout status statefulset/seaweedfs-volume --timeout=300s
kubectl -n s3 rollout status statefulset/seaweedfs-filer --timeout=300s
kubectl -n s3 rollout status deployment/seaweedfs-s3 --timeout=300s
kubectl -n s3 get pvc
kubectl -n s3 get service seaweedfs-s3
```

Require all claims to be `Bound` and all workloads ready. Local-path may use
`WaitForFirstConsumer`: claims can remain Pending until their pod is scheduled.
The master persists its Raft data/identity, filer persists embedded LevelDB2
metadata under `/data`, and the volume server persists object bytes/index together.
Logs use disposable `emptyDir`; log survival is not data survival.

For optional NodePort on the **fresh installation**, use this **instead of** the
`helm install` above:

```bash
helm install seaweedfs "$SEAWEEDFS_CHART" --namespace s3 \
  -f examples/seaweedfs/values.yaml \
  -f examples/seaweedfs/nodeport-values.yaml --wait --timeout 10m
kubectl -n s3 get service seaweedfs-s3
```

Ensure port 32333 is allowed by the cluster's NodePort range, unused, routed and
firewalled. It is **plain HTTP**, trusted-LAN-only, not Internet-safe. Protect
traffic using a separate TLS design before crossing untrusted networks. Do not
expose internal management services. The internal endpoint remains unchanged.

## 4. Reach S3 and configure clients without printing keys

In-cluster endpoint (default `cluster.local` DNS suffix):

```text
http://seaweedfs-s3.s3.svc.cluster.local:8333
```

For a workstation, the safer default is a loopback port-forward, in a separate
terminal (keep it running):

```bash
kubectl -n s3 port-forward --address 127.0.0.1 service/seaweedfs-s3 8333:8333
```

In the client terminal, from the repository root:

```bash
export SEAWEEDFS_AUTH_DIR="$HOME/.config/seaweedfs-small-lab"
export AWS_SHARED_CREDENTIALS_FILE="$SEAWEEDFS_AUTH_DIR/credentials"
export AWS_CONFIG_FILE="$SEAWEEDFS_AUTH_DIR/config"
export AWS_PROFILE=seaweedfs-lab
export AWS_DEFAULT_REGION=us-east-1
export AWS_EC2_METADATA_DISABLED=true
export AWS_PAGER=""
# Remove inherited credentials which could override the selected private profile.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
export S3_ENDPOINT=http://127.0.0.1:8333
python3 -m venv "$SEAWEEDFS_AUTH_DIR/venv"
"$SEAWEEDFS_AUTH_DIR/venv/bin/python" -m pip install boto3
```

For an authorized LAN NodePort client, replace only the endpoint:

```bash
: "${NODE_IP:?Set NODE_IP to a reachable lab node address}"
export S3_ENDPOINT="http://${NODE_IP}:32333"
```

For clients running inside Kubernetes use the internal endpoint and securely
supply the same generated keys through an application-specific Secret; do not
assume a workstation profile exists in pods. Configure **path-style addressing**,
**AWS SigV4**, region **`us-east-1`**. Do not add a virtual-hosted bucket prefix to
the hostname. InfluxDB's application-specific S3 settings/credential Secret must
match these choices; this guide does not create or modify an InfluxDB release.

## 5. Create bucket `lab` and verify exact object I/O

Boto3 route (uses the private AWS profile above):

```bash
"$SEAWEEDFS_AUTH_DIR/venv/bin/python" scripts/verify_s3.py \
  --endpoint "$S3_ENDPOINT" --bucket lab --create-bucket
```

The verifier checks the bucket; only a not-found result permits creation. For
`us-east-1` it omits `CreateBucketConfiguration/LocationConstraint`. It uploads a
unique object under `small-lab-verification/`, downloads and compares the **exact
bytes**, deletes that object in a `finally` block, and requires subsequent HEAD
to return not-found. It never deletes the bucket or any preexisting objects.
A failed request/byte comparison exits nonzero; printed PASS lines before a
later error do not imply overall success. If DELETE fails, inspect/clean the
unique test prefix privately. This is not a throughput or durability benchmark.

Expected output **when you run it successfully** (not observed against a fresh
installation during authoring):

```text
PUT: PASS
GET and byte comparison: PASS
DELETE and subsequent HEAD not-found: PASS
```

AWS CLI alternative, with the same private profile/config and endpoint:

```bash
# Fresh bucket only; fail on errors rather than interpreting every error as missing.
aws --endpoint-url "$S3_ENDPOINT" s3api create-bucket --bucket lab
# If the bucket already exists, omit create-bucket only after confirming ownership.
aws --endpoint-url "$S3_ENDPOINT" s3api head-bucket --bucket lab
(
  set -euo pipefail
  umask 077
  WORK="$(mktemp -d)"
  trap 'rm -rf "$WORK"' EXIT
  KEY="small-lab-verification/$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
  printf 'SeaweedFS CLI object verification\n' > "$WORK/input"
  aws --endpoint-url "$S3_ENDPOINT" s3api put-object \
    --bucket lab --key "$KEY" --body "$WORK/input" >/dev/null
  aws --endpoint-url "$S3_ENDPOINT" s3api get-object \
    --bucket lab --key "$KEY" "$WORK/output" >/dev/null
  cmp "$WORK/input" "$WORK/output"
  aws --endpoint-url "$S3_ENDPOINT" s3api delete-object --bucket lab --key "$KEY"
  # Require 404/NoSuchKey, NOT just an arbitrary nonzero exit (403/timeout is failure).
  if aws --endpoint-url "$S3_ENDPOINT" s3api head-object \
      --bucket lab --key "$KEY" >"$WORK/head.out" 2>"$WORK/head.err"; then
    printf 'FAIL: object still exists\n' >&2; exit 1
  fi
  python3 - "$WORK/head.err" <<'PY'
import pathlib, sys
message = pathlib.Path(sys.argv[1]).read_text()
if '(404)' not in message and '(NoSuchKey)' not in message:
    raise SystemExit('FAIL: HEAD failed for a reason other than not-found')
print('CLI PUT/GET exact-byte comparison/DELETE/not-found: PASS')
PY
)
```

If the CLI block fails before DELETE, it can leave its unique object; the Python
verifier has stronger cleanup behavior and is preferred. Do not retry a failing
create-bucket by disabling authentication. As an extra authentication check,
`aws --no-sign-request --endpoint-url "$S3_ENDPOINT" s3api list-buckets` must fail
with an authorization error; a timeout is not proof that anonymous access is denied.

## Existing releases: preserve credentials, storage and replica intent

Do not rerun fresh-install defaults over an existing release. Privately back up
its Helm revision/values, S3 Secrets, PVC identities and storage settings; use
restricted files outside Git and do not paste their contents into tickets.
Compare the release-rendered resources **and live resources** against the new
render, including pod templates, Secret references, claim templates, services
and replica counts. Stop on immutable-storage changes or unexpected rollouts.

The audited chart's generated S3 Secret is a **`pre-install,pre-upgrade` hook**
with `helm.sh/resource-policy: keep`. With no `existingConfigSecret`, the chart
supports inline admin/read credential pairs or generates missing credentials.
The helper `seaweedfs.getOrGeneratePassword` tries `lookup` of existing Secret
keys, otherwise uses random generation. An offline template has no Secret
lookup and can generate different values/checksums on repeated renders. Missing
read credentials/keys, renamed Secrets, incomplete preservation, or failed hooks
can change read credentials even when admin credentials were preserved. The
filer and gateway compute checksum annotations from the S3 Secret template or
lookup: unexpected credential changes can also trigger workload rollouts.
`keep` is not a promise that a hook cannot mutate/replace data, and an upgrade
failure is not proof that no hooks or resource writes occurred.

For a **narrow Service-only change on an existing release**, `--no-hooks` can be
appropriate **only after** all required Secrets already exist, their credential
material and all existing release settings are preserved, and the rendered/live
diff has been reviewed. Conceptual command with operator-supplied private paths:

```bash
: "${SEAWEEDFS_CHART:?Set pinned chart path}"
: "${PRESERVED_VALUES:?Set private complete reviewed values path}"
: "${REVIEWED_SERVICE_OVERLAY:?Set reviewed Service-only overlay path}"
helm upgrade seaweedfs "$SEAWEEDFS_CHART" --namespace s3 \
  -f "$PRESERVED_VALUES" -f "$REVIEWED_SERVICE_OVERLAY" \
  --no-hooks --wait --timeout 10m
```

This is **not** a fresh-install shortcut, migration recipe or generic upgrade
flag. It skips *all* hooks, including necessary bucket/provisioning/resize jobs
if those were enabled. It does not stop non-hook Secrets or checksum/template
changes, and `--reuse-values` alone does not reconcile live drift. Recheck exact
Secret references, Service selectors/ports/ClusterIP, controller revisions and
signed object I/O afterward. Preserve/restore credentials privately if a prior
failed upgrade already changed them; do not force ownership to suppress conflicts.

**Worker replica drift:** worker is disabled with zero intended replicas here;
S3 does not require it. The chart worker Deployment uses `worker.replicas` when
`worker.enabled` is true (and requires an admin server). A manually scaled live
worker can differ from Helm's stored replica count; a subsequent upgrade can
undo that scale or hit server-side-apply ownership conflicts. If maintaining an
existing enabled worker, record the intended count in that release's values and
review admin/worker settings. Do not accidentally enable workers, restore an old
count, or use force-conflicts as a workaround during a Service-only change.

## Persistence and operational limits

- One master, one filer and one volume server, replication `000`: **no HA and no
  redundant object copies**. Node/disk failure can make the store unavailable or
  destroy data. Increasing gateway replicas alone does not fix this.
- Local-path PV node affinity keeps pods attached to their storage node; it does
  not move data to another node. A failed node normally leaves dependent pods
  Pending/unavailable rather than transparently failing over. Replacing claims
  or bypassing affinity does not recover their data.
- Back up filer metadata, volume data/index, master state and credential config
  consistently using a separately tested recovery plan. PVC persistence across
  pod replacement is not a backup. Do not delete PVCs, namespace, or reinstall to
  fix authentication. Reclaim policies may delete underlying files.
- Claim-template/storage-layout changes often cannot be upgraded in place;
  expansion depends on StorageClass support and is not automated by this example.
- Disk exhaustion, OOM limits, permissions or Pending PVCs can prevent writes
  even when S3 TCP/HTTP health is up. Inspect events/rollouts privately and run
  signed PUT/GET/DELETE after changes. A ready pod or unauthenticated HTTP 200 is
  not proof that the authenticated bucket workflow works.
- This HTTP, single-copy object store is for disposable experiments, not a
  supported production InfluxDB storage/durability design. Fresh deployment,
  recovery, authentication rejection, real SDK roundtrip and restart durability
  remain operator acceptance tests, not claims made by template validation.
