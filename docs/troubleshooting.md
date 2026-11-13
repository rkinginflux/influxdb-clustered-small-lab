# Troubleshooting the small Clustered lab

Diagnose first; do not reinstall or delete data as a default repair. Commands
below are read-only unless explicitly described otherwise. Select the intended
kubeconfig/context as in [the installation guide](clustered.md).

```bash
kubectl config current-context
kubectl -n influxdb3-clustered get deploy,statefulset,pods,pvc
kubectl -n influxdb3-clustered get events --field-selector type=Warning --sort-by=.lastTimestamp
kubectl -n kubit logs deployment/kubit --tail=60
kubectl -n influxdb3-clustered logs deployment/license-controller --tail=40
```

Logs and pod descriptions can contain sensitive information. Review and redact
locally before sharing. Never dump all Secrets or full Helm values to an issue.

## Helm succeeded but database Services/pods do not exist

The chart installs kubit and an AppInstance. Database resources are generated
asynchronously from the licensed OCI package. Inspect AppInstance **conditions**,
operator logs and temporary apply/render Jobs; a green Helm release does not
establish database readiness.

```bash
kubectl -n influxdb3-clustered get appinstance influxdb3-clustered \
  -o jsonpath='{.status.conditions}'
kubectl -n influxdb3-clustered get jobs
kubectl -n kubit get pods
```

A completed then deleted apply Job can be normal cleanup, not a server restart.
Repeated new successful Jobs with unchanged generation indicate reconciliation
churn, not by themselves an IOx outage or a proven root cause. Correlate Job
exit status, AppInstance generation and application restarts. Do not pause the
operator or delete Jobs as a claimed fix without evidence.

## ImagePullBackOff, missing pull Secret, OCI unauthorized

Check events for the exact failing registry and image. `gar-docker-secret` must
exist in **both** `kubit` and `influxdb3-clustered`; names alone do not verify
permissions. Confirm the issued identity's access without printing its contents:

```bash
kubectl -n kubit get secret gar-docker-secret -o name
kubectl -n influxdb3-clustered get secret gar-docker-secret -o name
kubectl -n influxdb3-clustered get pods \
  -o custom-columns='POD:.metadata.name,IMAGES:.spec.containers[*].image'
```

Check registry egress, hostname coverage, expiration and entitlement. Downloading
a public chart does not grant package/image access. Keep chart `0.1.28` and
package `20261016-2070790` explicit; do not solve authorization with a random
package tag. Never put registry JSON or a license into a public bug report.

## CrashLoopBackOff / exit 132 / Illegal instruction

Verify CPU features on the **scheduled worker/VM**, not the workstation.
AVX without AVX2 is not sufficient for the reference IOx image. Compare with a
known-compatible worker. Exit 132 suggests an illegal instruction; it does not
identify the instruction or exclude another root cause.

```bash
kubectl get nodes -l lab.example.com/influxdb-avx2=true
kubectl -n influxdb3-clustered get pods -o wide
```

Check selectors for ingester, querier, compactor, router, catalog **and GC**.
Never label an incompatible node to get a Pending pod scheduled. Correct durable
values before an intentional rollout. A node-local WAL PVC may constrain where
an ingester can move; changing a label is not a storage migration.

## Catalog Pending, one ready peer, quorum/write failure

Keep **three catalogs** and at least **three distinct eligible schedulable
nodes**. Check anti-affinity/topology, hostname uniqueness, taints/tolerations,
CPU labels, resource availability, peer endpoints and PostgreSQL connectivity.
A single ready catalog pod does not establish a functioning three-peer system.

```bash
kubectl -n influxdb3-clustered get statefulset iox-shared-catalog
kubectl -n influxdb3-clustered get pods -o wide
kubectl -n influxdb3-clustered get statefulset iox-shared-catalog \
  -o jsonpath='{.spec.template.spec.affinity}'
kubectl describe nodes -l lab.example.com/influxdb-avx2=true
```

Inspect bounded pod events/logs locally as needed. Do not lower the catalog
replica count or force all peers onto one hostname. Increasing replica count
beyond three is not the intended fix either.

## PostgreSQL `role "root" does not exist`, yet Ready

A default `pg_isready` may select OS user root; readiness can still succeed and
leave misleading role errors. The starter manifest intentionally uses:

```yaml
exec:
  command: ['sh', '-ec', 'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"']
```

Kubelet static `$(VAR)` substitution does not resolve Secret-backed values as a
shell would. Expand the variables inside `sh -ec`, quoted. Verify a real
password-authenticated `SELECT 1` using the guide's command, then observe logs
across several probe intervals. Readiness is not proof of valid catalog auth.

If an existing database rejects the generated password, **stop**. Updating
`POSTGRES_PASSWORD` in a Secret does not rotate the role in an initialized PVC.
Recover the correct credentials or plan an authenticated SQL rotation with
coordinated DSN updates. Do not rerun credential generation or delete the PVC.
The helper's file-exists failure is intentional overwrite protection.

## License missing, expired or controller failing

Check `iox-license` by name and inspect bounded license-controller logs. Confirm
the supplied License object's namespace and that its CRD was installed first.
A valid, authorized license must come from InfluxData; there is no sample license
or bypass in this repository. Follow the official
[license management guide](https://docs.influxdata.com/influxdb3/clustered/admin/licensing/).
Do not print the License or derived Secret.

## S3 auth failures, AccessDenied, wrong endpoint

The configured Service DNS is internal:
`http://seaweedfs-s3.s3.svc.cluster.local:8333`. A workstation may not resolve or
route that address; do not replace it with localhost or a temporary port-forward
in Clustered's values. Check Service/EndpointSlices and DNS from the cluster:

```bash
kubectl -n s3 get service seaweedfs-s3
kubectl -n s3 get endpointslice -l kubernetes.io/service-name=seaweedfs-s3
kubectl -n s3 get pods
```

Check that bucket `lab` exists and credentials grant write/read/delete plus
required listing/multipart permissions, not just bucket listing. SeaweedFS JSON
may contain `${...}` references: resolve the actual backing identity, never copy
the placeholder literally. Check region and endpoint against your deployment.
HTTP requires explicit `allowHttp: "true"`; that permits cleartext, not TLS.

Use signed PUT/GET/DELETE of a dedicated disposable object to distinguish
credential/permissions failures from superficial HTTP health. Do not overwrite
live object-store keys or rerun credential-generation hooks blindly to fix a
Service change. Do not delete or empty the database bucket.

## Gateway health passes but write/query fails

`/healthz` is a static NGINX response. Inspect application readiness, Service
ports and EndpointSlices. The actual upstreams are management `core:8091/9091`,
write `global-router:8080`, InfluxQL `iox-shared-querier:8081` and Flight
`iox-shared-querier:8082`. Never replace them with standalone port 8181.

```bash
kubectl -n influxdb3-clustered get service core global-router iox-shared-querier
kubectl -n influxdb3-clustered get endpointslice
kubectl -n influxdb3-clustered logs deployment/clustered-gateway --tail=40
```

The default upstream route is management **gRPC**, not an HTTP landing page;
there is no bundled database browser UI here. For SQL failures verify HTTP/2,
Flight service path and port, plus token scope. Do not share upstream keepalive
pools between HTTP/1 proxying and HTTP/2 gRPC. Avoid automatic retries of ambiguous
write operations. This lab proxy disables write and management-gRPC retry paths.

## TLS, localhost forwarding and self-signed trust

Keep the port-forward running in a second terminal with the same kubeconfig;
make sure local port 8443 is free. Use `https://localhost:8443`, matching the
certificate SAN. Verify with `curl --cacert "$LOCAL/tls.crt"`, then the CLI
profile's absolute `profile.tls.ca` path. CA trust, hostname mismatch, certificate
expiry and token authorization are separate problems. Reissue/review a matching
certificate rather than leaving `insecure=true`, `disable=true` or `curl -k`.
`disable` means HTTP instead of HTTPS; it is not a CA setting. Restrict forwarding
to `127.0.0.1`, not `0.0.0.0`. Proxy TLS does not encrypt the backend/S3/PG hops.

## Management works, data returns 401/invalid token

Use `management.toml` to create databases/tokens and `data.toml` for write/query.
The database token must have read and write scope for the actual database name.
Do not paste the bootstrap management token into a data-token field. Allow the
bounded propagation retry from the guide (roughly ten-second refresh observed
in the reference lab). Retry only an initial invalid-token result; continuing
401s, scope failures, connection failures and TLS errors require diagnosis.
Never print token-create JSON to shared logs or mint a token on every retry.

## OOMKilled, resource pressure, failed PVC binding

The values are smoke-test settings, not production recommendations. Inspect
requests, limits, usage (if metrics-server is available), events and PVC topology:

```bash
kubectl -n influxdb3-clustered get pvc
kubectl get storageclass local-path
kubectl -n influxdb3-clustered top pods
```

`top` can fail without metrics-server; that is not a database health test.
The documented resource subtotal excludes default package services, sidecars,
GC, monitoring and transient Jobs. Increase memory for measured peaks and leave
node headroom; do not make replicas smaller by breaking catalog quorum. A
WaitForFirstConsumer PVC may remain Pending until scheduling can be satisfied.
Inspect local provisioner health, disk space, affinity and permissions. Never
change a populated claim to fresh storage and call it migration.

## Stuck rollout / ingester shutdown

An early empty-lab recovery does not establish safe forced termination of a
populated ingester. Listener closure or a log saying persistence started/completed
is not proof that the process exited cleanly. Preserve WAL/catalog/object data;
allow graceful shutdown and use version-specific guidance before changing grace
periods or force-deleting pods. A stale StatefulSet revision may require explicit
pod recreation after the source is corrected, but that is an intentional
state-changing recovery step with data-risk review, not a blanket instruction.

## Before sharing a report

Share pinned versions, redacted conditions/events, controller readiness,
namespace/service names and a synthetic failing request. Exclude private inputs,
full profiles, tokens, licenses, Docker config, credential-bearing DSNs, customer
data, private hostnames/IPs and unreviewed screenshots. Local PVs and singleton
services are not HA: preserve data and validate a restore plan before destructive
experiments. There is no destructive cleanup command in this guide.
