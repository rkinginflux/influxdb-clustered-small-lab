#!/usr/bin/env python3
"""Generate only locally owned Grafana resources from an authorized package render.

Does not apply anything, read credentials or enable the live Grafana feature flag.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

import yaml
from grafana_style import style_dashboard


def render(source, namespace, public_url):
    parsed = urlparse(public_url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('Use an HTTPS public URL without credentials')
    objects = []
    for path in sorted(source.glob('*.yaml')):
        for obj in yaml.safe_load_all(path.read_text()):
            if not obj:
                continue
            name, kind = obj['metadata']['name'], obj['kind']
            if name.startswith('grafana-dashboard-') and kind == 'ConfigMap':
                obj['metadata']['name'] = name.replace('grafana-dashboard-', 'grafana-lab-dashboard-', 1)
                for key, value in obj['data'].items():
                    dashboard = json.loads(value)
                    for variable in dashboard.get('templating', {}).get('list', []):
                        if variable['name'] == 'namespace':
                            variable['current'] = {'selected': True, 'text': namespace, 'value': namespace}
                        elif variable['type'] == 'datasource':
                            variable['current'] = {'selected': True, 'text': 'prometheus', 'value': 'P1809F7CD0C75ACF3'}
                    obj['data'][key] = json.dumps(style_dashboard(dashboard))
                objects.append(obj)
            elif name == 'grafana' and kind in ['Deployment', 'Service', 'ServiceAccount']:
                objects.append(obj)
            elif name in ['grafana-config', 'grafana-datasources', 'grafana-dashboards'] and kind in ['Secret', 'ConfigMap']:
                objects.append(obj)
    deployments = [o for o in objects if o['kind'] == 'Deployment']
    assert len(deployments) == 1, 'Expected exactly one bundled Grafana deployment'
    assert sum(o['metadata']['name'].startswith('grafana-lab-dashboard-') for o in objects) == 9
    for obj in objects:
        obj['metadata']['namespace'] = namespace
    datasource = next(o for o in objects if o['metadata']['name'] == 'grafana-datasources')
    content = json.loads(datasource['stringData']['datasources.yaml'])
    content['datasources'][0].update({'uid': 'P1809F7CD0C75ACF3', 'isDefault': True})
    datasource['stringData']['datasources.yaml'] = json.dumps(content)
    deployment = deployments[0]
    deployment['spec']['strategy'] = {'type': 'Recreate'}
    template = deployment['spec']['template']
    template.setdefault('metadata', {}).setdefault('annotations', {})['checksum/grafana-datasources'] = hashlib.sha256(json.dumps(datasource, sort_keys=True).encode()).hexdigest()
    spec = template['spec']
    spec['imagePullSecrets'] = [{'name': 'gar-docker-secret'}]
    container = next(c for c in spec['containers'] if c['name'] == 'grafana')
    env = {e['name']: e for e in container.get('env', []) if 'LIFETME' not in e['name']}
    for key, value in {
        'GF_SERVER_DOMAIN': parsed.hostname, 'GF_SERVER_ROOT_URL': public_url.rstrip('/') + '/',
        'GF_SECURITY_COOKIE_SECURE': 'true', 'GF_USERS_ALLOW_SIGN_UP': 'false',
        'GF_AUTH_ANONYMOUS_ENABLED': 'false', 'GF_AUTH_LOGIN_MAXIMUM_INACTIVE_LIFETIME_DAYS': '1',
        'GF_AUTH_LOGIN_MAXIMUM_LIFETIME_DAYS': '1',
    }.items():
        env[key] = {'name': key, 'value': value}
    for name, key in [('GF_SECURITY_ADMIN_USER', 'username'), ('GF_SECURITY_ADMIN_PASSWORD', 'password')]:
        env[name] = {'name': name, 'valueFrom': {'secretKeyRef': {'name': 'grafana-admin', 'key': key}}}
    container['env'] = list(env.values())
    container['resources'] = {'requests': {'cpu': '100m', 'memory': '256Mi'}, 'limits': {'cpu': '500m', 'memory': '1Gi'}}
    for volume in spec['volumes']:
        if volume.get('configMap', {}).get('name', '').startswith('grafana-dashboard-'):
            volume['configMap']['name'] = volume['configMap']['name'].replace('grafana-dashboard-', 'grafana-lab-dashboard-', 1)
        if volume['name'] == 'grafana-storage':
            volume.pop('emptyDir', None)
            volume['persistentVolumeClaim'] = {'claimName': 'grafana-data'}
    return objects


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-dir', required=True, type=Path)
    parser.add_argument('--public-url', required=True)
    parser.add_argument('--namespace', default='influxdb3-clustered')
    parser.add_argument('--output', type=Path, default=Path('.private/grafana-bundled.yaml'))
    args = parser.parse_args()
    objects = render(args.manifest_dir, args.namespace, args.public_url)
    args.output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    args.output.write_text('# Generated locally from the authorized installed package. Do not publish.\n' + yaml.safe_dump_all(objects, sort_keys=False))
    args.output.chmod(0o600)
    print('Generated Grafana-only resources at', args.output)


if __name__ == '__main__':
    main()
