# Security and publication boundaries

This is an educational, trusted-LAN lab, not a hardened production deployment.
Do not expose its NodePorts to the public Internet.

- Obtain your own Clustered license and registry credentials from InfluxData.
- Generate S3, PostgreSQL, Grafana and data-token credentials locally. Never use
  passwords copied from a public example.
- Keep generated files in ignored `.private/` directories with restrictive modes.
- Do not commit license files, kubeconfigs, Docker auth JSON, database DSNs with
  passwords, private keys, datasource tokens, rendered private package contents,
  database snapshots, Helm release dumps or shell recordings containing secrets.
- Use distinct management, write-only collector and read-only dashboard tokens.
- Validate TLS with your trusted lab CA. A self-signed CA requires explicit trust;
  turning off database TLS verification is not a substitute.
- Plain HTTP S3 and PostgreSQL connections inside this example cluster are lab
  limitations. Add encryption/network policies and proper secret management for
  any environment with stronger security requirements.
- Kubelet TLS verification is disabled in the supplied collector values only
  for that scrape. Prefer trusted kubelet certificates instead.
- A local-path PVC is persistent, not highly available and not a backup.
- Avoid deleting volumes/buckets to work around startup, auth or upgrade errors.

`validate_repo.py` includes basic credential/private-topology checks, but is not
an exhaustive secret detector. Review the full staged diff before every public
push and use your organization's approved secret scanner as well. Secret/key
names and examples of environment-variable references are not credentials.

Screenshots show actual lab metrics; visible host labels were anonymized and
no credential/session material is included. Do not publish your own screenshots
until you inspect browser chrome, variables, query editors, legends and tooltips
for private endpoints, customer identifiers and tokens.

Report guide defects through repository issues. Do not include secrets in an
issue. If a credential is accidentally published, revoke/rotate it immediately;
deleting the visible line does not remove it from Git history.
