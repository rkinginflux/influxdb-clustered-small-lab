#!/usr/bin/env python3
"""Offline checks only. Pass an externally obtained chart directory/archive.

Requires Python 3.11+, PyYAML and Helm. No kubectl, registry credentials or cluster
access. Temporary test credentials and synthetic profile inputs are deleted.
"""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import tomllib
from urllib.parse import urlsplit, unquote

import yaml


def run(args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chart', required=True, help='Pinned official chart directory or tgz')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    examples = root / 'examples'
    local = examples / 'clustered/.local'
    local.mkdir(parents=True, mode=0o700, exist_ok=True)
    chart = yaml.safe_load(run(['helm', 'show', 'chart', args.chart]).stdout)
    assert chart['version'] == '0.1.28'
    assert str(chart['appVersion']) == '20261016-2070790'
    values = yaml.safe_load((examples / 'clustered/values.yaml').read_text())
    assert values['image']['tag'] == '20261016-2070790'
    assert values['operatorImageVersion'] == 'v0.0.22'
    assert values['resources']['catalog']['requests']['replicas'] == 3
    for role in ['ingester', 'querier', 'compactor', 'catalog', 'router', 'garbage-collector']:
        assert values['components'][role]['template']['nodeSelector'] == {
            'lab.example.com/influxdb-avx2': 'true'}
    print(run(['helm', 'lint', args.chart, '-f', str(examples / 'clustered/values.yaml')]).stdout.strip())
    rendered = list(yaml.safe_load_all(run(['helm', 'template', 'influxdb3-clustered', args.chart,
        '--namespace', 'influxdb3-clustered', '-f', str(examples / 'clustered/values.yaml')]).stdout))
    app = next(x for x in rendered if x and x['kind'] == 'AppInstance')
    assert app['spec']['package']['image'].endswith(':20261016-2070790')
    assert app['spec']['package']['spec']['resources']['catalog']['requests']['replicas'] == 3
    count = 0
    for relative in ['clustered/values.yaml', 'postgres/postgres.yaml', 'gateway/gateway.yaml']:
        path = examples / relative
        objects = list(yaml.safe_load_all(path.read_text()))
        assert all(not obj or obj.get('kind') != 'Secret' for obj in objects)
        count += len(objects)
    postgres = list(yaml.safe_load_all((examples / 'postgres/postgres.yaml').read_text()))
    sts = next(x for x in postgres if x['kind'] == 'StatefulSet')
    pod = sts['spec']['template']['spec']
    container = pod['containers'][0]
    assert container['envFrom'][0]['secretRef']['name'] == 'influxdb3-postgres-auth'
    probe = container['readinessProbe']['exec']['command']
    assert probe == ['sh', '-ec', 'exec pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"']
    # Exercise actual shell expansion with a harmless local pg_isready stand-in.
    with tempfile.TemporaryDirectory(prefix='offline-check-', dir=local) as tmp:
        tmp = Path(tmp)
        fake = tmp / 'pg_isready'
        fake.write_text('#!/bin/sh\ntest "$1" = -U && test "$2" = fixture_user && test "$3" = -d && test "$4" = fixture_db\n')
        fake.chmod(0o700)
        env = dict(os.environ, PATH=str(tmp) + os.pathsep + os.environ['PATH'],
                   POSTGRES_USER='fixture_user', POSTGRES_DB='fixture_db')
        run(probe, env=env)
        sandbox = tmp / 'sandbox'
        for rel in ['examples/postgres/generate-auth.py', 'examples/clustered/profiles.py']:
            dest = sandbox / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / rel, dest)
        script = sandbox / 'examples/postgres/generate-auth.py'
        run(['python3', str(script)])
        private = sandbox / 'examples/clustered/.local'
        path = private / 'postgres-secrets.json'
        assert path.stat().st_mode & 0o777 == 0o600
        assert private.stat().st_mode & 0o777 == 0o700
        objs = json.loads(path.read_text())['items']
        auth = objs[0]['stringData']
        dsn = urlsplit(objs[1]['stringData']['dsn'])
        assert unquote(dsn.password) == auth['POSTGRES_PASSWORD']
        assert dsn.hostname == 'influxdb3-postgres'
        assert objs[1]['stringData'] == objs[2]['stringData']
        assert subprocess.run(['python3', str(script)], capture_output=True).returncode != 0
        # Explicit synthetic unit fixture, never a response from a real API.
        (private / 'data-token.json').write_text(json.dumps({'token': 'synthetic-offline-fixture'}))
        profile_script = sandbox / 'examples/clustered/profiles.py'
        for mode in ['management', 'data']:
            run(['python3', str(profile_script), mode])
            p = private / (mode + '.toml')
            assert p.stat().st_mode & 0o777 == 0o600
            profile = tomllib.loads(p.read_text())['profile'][0]
            assert profile['host'] == 'localhost' and profile['port'] == '8443'
            assert profile['tls']['ca'] == str(private / 'tls.crt')
            if mode == 'data':
                assert profile['token'] == 'synthetic-offline-fixture'
                assert profile['auth']['token']['token_file'] == str(private / 'admin-token.json')
            else:
                assert profile['auth']['token']['token_file'] == str(private / 'admin-token.json')
                assert 'token' not in profile
            assert subprocess.run(['python3', str(profile_script), mode], capture_output=True).returncode != 0
    gateway = list(yaml.safe_load_all((examples / 'gateway/gateway.yaml').read_text()))
    config = next(x for x in gateway if x['kind'] == 'ConfigMap')['data']['default.conf']
    assert 'http2 on;' in config and 'access_log off;' in config
    for route in ['core:9091', 'core:8091', 'global-router:8080',
                  'iox-shared-querier:8081', 'iox-shared-querier:8082']:
        assert route in config
    service = next(x for x in gateway if x['kind'] == 'Service')
    deployment = next(x for x in gateway if x['kind'] == 'Deployment')
    assert service['spec']['type'] == 'ClusterIP'
    labels = deployment['spec']['template']['metadata']['labels']
    assert all(labels[k] == v for k, v in service['spec']['selector'].items())
    governing = next(x for x in postgres if x['metadata']['name'] == sts['spec']['serviceName'])
    assert governing['spec']['clusterIP'] == 'None'
    for service in [x for x in postgres if x['kind'] == 'Service']:
        labels = sts['spec']['template']['metadata']['labels']
        assert all(labels[k] == v for k, v in service['spec']['selector'].items())
    requests_cpu = sum(int(r['requests']['cpu'][:-1]) * r['requests']['replicas']
                       for r in values['resources'].values())
    requests_mi = sum(int(r['requests']['memory'][:-2]) * r['requests']['replicas']
                      for r in values['resources'].values())
    limits_cpu = sum(float(r['limits']['cpu'][:-1]) / 1000 * r['requests']['replicas']
                     if r['limits']['cpu'].endswith('m') else float(r['limits']['cpu']) * r['requests']['replicas']
                     for r in values['resources'].values())
    limits_gi = sum(int(r['limits']['memory'][:-2]) * r['requests']['replicas']
                    for r in values['resources'].values())
    assert (requests_cpu, requests_mi, limits_cpu, limits_gi) == (700, 3584, 5, 10)
    print(f'Explicit IOx subtotal: {requests_cpu}m CPU/{requests_mi}Mi requests; {limits_cpu:g} CPU/{limits_gi}Gi limits')
    print(f'Including PG/gateway/kubit only: {requests_cpu + 100 + 25 + 10}m CPU/{requests_mi + 256 + 32 + 64}Mi requests; '
          f'{limits_cpu + 1 + 0.5 + 0.5:g} CPU/{limits_gi * 1024 + 1024 + 128 + 128}Mi limits')
    blocks = 0
    for path in [root / 'docs/clustered.md', root / 'docs/prerequisites.md', root / 'docs/troubleshooting.md']:
        for block in re.findall(r'```bash\n(.*?)```', path.read_text(), re.S):
            run(['bash', '-n'], input=block)
            for python in re.findall(r"<<'PY'\n(.*?)\nPY(?:\n|$)", block, re.S):
                ast.parse(python)
            blocks += 1
    print(f'PASS: {count} public YAML documents, Helm AppInstance render, helper generation/overwrite protection, '
          f'permissions, TOML profiles, shell probe expansion, Service selectors, and {blocks} Bash blocks')
    print('OFFLINE ONLY: no cluster changes; no full OCI package-schema, NGINX runtime or fresh-install validation.')


if __name__ == '__main__':
    main()
