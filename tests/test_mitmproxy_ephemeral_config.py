"""Render regression gates for opt-in, PVC-independent mitmproxy rollouts."""
import json
from pathlib import Path
import re
import subprocess
import unittest

CHART = Path(__file__).resolve().parents[1] / 'chart'

def render(values):
    return subprocess.run(['helm', 'template', 'quarantine', str(CHART), '-f', '-'],
                          input=json.dumps(values), text=True, capture_output=True)

def deployment(text):
    return next(d for d in re.split(r'(?m)^---\s*$', text)
                if 'kind: Deployment\n' in d and 'name: mitmproxy-debug\n' in d)

class EphemeralProxyTests(unittest.TestCase):
    def test_ephemeral_config_removes_rwo_dependency_and_keeps_old_pvc(self):
        result = render({'mitmproxy': {'ephemeralConfig': True}, 'ca': {'enabled': True}})
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = deployment(result.stdout)
        self.assertIn('emptyDir:', spec)
        self.assertNotIn('persistentVolumeClaim:', spec)
        self.assertIn('type: RollingUpdate', spec)
        self.assertIn('maxSurge: 1', spec)
        self.assertIn('maxUnavailable: 0', spec)
        self.assertIn('readinessProbe:', spec)
        self.assertIn('startupProbe:', spec)
        self.assertIn('port: proxy', spec)
        self.assertIn('name: install-ca', spec)
        self.assertIn('secretName: mitmproxy-ca', spec)
        self.assertIn('kind: PersistentVolumeClaim', result.stdout)
        self.assertIn('name: mitmproxy-certs', result.stdout)

    def test_ephemeral_mode_without_stable_ca_fails_closed(self):
        result = render({'mitmproxy': {'ephemeralConfig': True}, 'ca': {'enabled': False}})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('requires ca.enabled', result.stderr)

    def test_legacy_mode_retains_recreate_and_pvc(self):
        result = render({'mitmproxy': {'ephemeralConfig': False}})
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = deployment(result.stdout)
        self.assertIn('type: Recreate', spec)
        self.assertIn('claimName: mitmproxy-certs', spec)
        self.assertNotIn('readinessProbe:', spec)
        self.assertNotIn('maxSurge:', spec)
        self.assertIn('stream_large_bodies=5m', spec)

    def test_ephemeral_init_rejects_empty_secret_files(self):
        result = render({'mitmproxy': {'ephemeralConfig': True}, 'ca': {'enabled': True}})
        self.assertEqual(result.returncode, 0, result.stderr)
        spec = deployment(result.stdout)
        self.assertIn('set -eu', spec)
        self.assertIn('umask 077', spec)
        self.assertIn('test -s /ca-secret/mitmproxy-ca-key.pem', spec)
        self.assertIn('test -s /ca-secret/mitmproxy-ca-cert.pem', spec)

if __name__ == '__main__':
    unittest.main()
