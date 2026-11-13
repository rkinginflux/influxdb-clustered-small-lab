#!/usr/bin/env python3
"""Generate NEW-lab PostgreSQL credentials locally, never print their values.

Does not contact Kubernetes. Refuses to overwrite credentials. Do not run this
against an initialized PostgreSQL PVC: changing a Secret does not rotate SQL roles.
"""
import json
import os
from pathlib import Path
import secrets
from urllib.parse import quote


def main():
    root = Path(__file__).resolve().parents[2]
    target = root / 'examples/clustered/.local'
    target.mkdir(mode=0o700, parents=True, exist_ok=True)
    target.chmod(0o700)
    user, database = 'clustered', 'clustered'
    password = secrets.token_urlsafe(36)
    dsn = (f'postgresql://{quote(user, safe="")}:{quote(password, safe="")}'
           f'@influxdb3-postgres:5432/{quote(database, safe="")}?sslmode=disable')
    def secret(name, data):
        return {'apiVersion': 'v1', 'kind': 'Secret',
                'metadata': {'name': name, 'namespace': 'influxdb3-clustered'},
                'type': 'Opaque', 'stringData': data}
    objects = [secret('influxdb3-postgres-auth', {
        'POSTGRES_USER': user, 'POSTGRES_DB': database, 'POSTGRES_PASSWORD': password}),
        secret('influxdb3-catalog-dsn', {'dsn': dsn}),
        secret('influxdb3-admin-dsn', {'dsn': dsn})]
    path = target / 'postgres-secrets.json'
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        json.dump({'apiVersion': 'v1', 'kind': 'List', 'items': objects}, f, indent=2)
    print('Generated private PostgreSQL Secret input (not applied).')


if __name__ == '__main__':
    main()
