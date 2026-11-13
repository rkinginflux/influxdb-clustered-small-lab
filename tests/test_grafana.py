import json
from pathlib import Path
import sys
import tempfile
import unittest

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from grafana_style import style_dashboard
from render_grafana import render


class GrafanaTests(unittest.TestCase):
    def test_styling_keeps_queries_thresholds_and_log_scales(self):
        original = {'panels': [{'type': 'timeseries', 'targets': [{'expr': 'rate(metric[5m])'}],
                    'fieldConfig': {'defaults': {'unit': 'bytes', 'thresholds': {'steps': []},
                    'custom': {'scaleDistribution': {'type': 'log'}, 'stacking': {'mode': 'normal'}}}}}]}
        styled = style_dashboard(original)
        self.assertEqual(styled['panels'][0]['targets'], original['panels'][0]['targets'])
        defaults = styled['panels'][0]['fieldConfig']['defaults']
        self.assertEqual(defaults['custom']['scaleDistribution']['type'], 'log')
        self.assertEqual(defaults['custom']['stacking']['mode'], 'normal')
        self.assertEqual(defaults['unit'], 'bytes')
        self.assertEqual(style_dashboard(styled), styled)

    def test_render_selects_only_grafana_and_secure_persistent_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            objects = [
                {'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': 'grafana'},
                 'spec': {'template': {'metadata': {}, 'spec': {'containers': [{'name': 'grafana'}],
                 'volumes': [{'name': 'grafana-storage', 'emptyDir': {}}]}}}},
                {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'grafana-datasources'},
                 'stringData': {'datasources.yaml': json.dumps({'datasources': [{'name': 'prometheus'}]})}},
                {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'unrelated-secret'}, 'stringData': {'not_exported': 'fixture'}},
            ]
            for i in range(9):
                objects.append({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': f'grafana-dashboard-fixture-{i}'},
                                'data': {f'{i}.json': json.dumps({'uid': f'fixture-{i}', 'panels': [], 'templating': {'list': []}})}})
            for i, obj in enumerate(objects):
                (source / f'{i}.yaml').write_text(yaml.safe_dump(obj))
            output = render(source, 'influxdb3-clustered', 'https://grafana.lab.example:32443')
            self.assertEqual(len(output), 11)
            self.assertFalse(any(o['metadata']['name'] == 'unrelated-secret' for o in output))
            deployment = next(o for o in output if o['kind'] == 'Deployment')
            self.assertEqual(deployment['spec']['strategy']['type'], 'Recreate')
            spec = deployment['spec']['template']['spec']
            self.assertEqual(spec['volumes'][0]['persistentVolumeClaim']['claimName'], 'grafana-data')
            env = {e['name']: e for e in spec['containers'][0]['env']}
            self.assertEqual(env['GF_AUTH_ANONYMOUS_ENABLED']['value'], 'false')
            self.assertEqual(env['GF_SECURITY_COOKIE_SECURE']['value'], 'true')
            self.assertIn('secretKeyRef', env['GF_SECURITY_ADMIN_PASSWORD']['valueFrom'])

    def test_reject_plain_http(self):
        with self.assertRaises(ValueError):
            render(Path('.'), 'influxdb3-clustered', 'http://grafana.lab.example')


if __name__ == '__main__':
    unittest.main()
