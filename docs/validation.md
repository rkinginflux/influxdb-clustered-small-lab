# Validation evidence and limitations

This repository documents a working reference lab and publishes generalized,
credential-free examples. It does not claim that the complete public recipe was
reinstalled on a separate empty Kubernetes cluster while preparing the guide.

## Working reference lab

During the original setup, real tool checks established:

- Distributed Clustered was installed and its gateway accepted scoped,
  authenticated writes and SQL/Flight queries.
- PostgreSQL, WAL, monitoring, Grafana and SeaweedFS storage persisted on PVCs.
- Actual data persisted as Parquet objects in the SeaweedFS bucket.
- Authenticated S3 PUT/GET/DELETE worked through the NodePort, including access
  through each node's LAN endpoint, without a workstation port-forward.
- Grafana login, disabled anonymous access, datasource health, operational
  dashboards and persistence across a deliberate Grafana restart were checked.
- Telegraf collected fresh host/kubelet data from all five nodes.
- Every one of the sixteen Telegraf panels returned actual numeric results for
  each individual host and All: **96 backend panel/host checks**.
- The PostgreSQL health-probe expansion fix removed repeated root-role errors;
  PostgreSQL remained ready and Clustered queries still succeeded.

These are observations about that lab, not a production support/SLA claim.

## Rechecked while preparing the public guide

- Grafana authentication/health, the original bundled dashboard set and the
  default Prometheus datasource passed the existing lab verifier.
- All 96 Telegraf panel/host backend checks passed again.
- The original `testdb.home` query still returned four rows.
- Two actual browser screenshots were captured at 1600×1100 and inspected.
  Host labels in the Telegraf screenshot were anonymized; recorded values were
  not fabricated or altered. Optional missing router metrics remain visible.
- The public Grafana render helper was exercised against the authorized package
  render, generating Grafana-only resources into a private, unpublished file.
- Synthetic unit tests cover render selection, private Secret references,
  persistent storage/authentication settings, HTTPS requirements and preservation
  of query/threshold/logarithmic-scale semantics.

## Public example checks

`python scripts/validate_repo.py` checks local Markdown links, shell-block syntax,
Python syntax, YAML/JSON parsing, screenshot PNG signatures, and basic secret/
private-topology patterns. It does not run deployment blocks or send Kubernetes
API requests. CI runs the same offline validation and synthetic unit tests.

Helm lint/template validation is separate from installation. The pinned public
chart schemas and rendered storage/authentication references were inspected
against the vendored reference versions during preparation. See the individual
SeaweedFS and Clustered guides for the exact lint/template commands and gates.

A successful render does not establish that your nodes can pull private images,
that a license is valid, that Kubernetes admission policy permits the resources,
or that a workload has sufficient CPU/memory/disk under real load.

## Not validated or promised

- A fresh full install from these generalized examples on another cluster.
- Production throughput, latency or resource sizing.
- Storage HA, node-loss recovery, disaster recovery or off-cluster backups.
- A Kubernetes control-plane/CNI/storage-provisioner bootstrap.
- Public Internet exposure, production PKI or a hardened network-policy design.
- Every optional service-mesh/exporter panel populated with metrics.
- Compatibility with arbitrary future package/chart versions or other CPU types.

The reference SeaweedFS service already existed before the Clustered work. The
new fresh-install SeaweedFS instructions are a chart-inspected/render-validated
recipe, not a claim that the original S3 service was created from those exact
new instructions. Do not substitute an upgrade command for the fresh-install
procedure, or vice versa.
