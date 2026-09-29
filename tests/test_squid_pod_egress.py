"""Regression gates for narrowly scoped Squid egress after Gateway VIP DNAT.

Run with: python3 -m unittest discover -s tests -p 'test_squid_pod_egress.py'
Requires helm on PATH; no third-party Python packages.
"""
import json
import pathlib
import re
import subprocess
import tempfile
import unittest


CHART = pathlib.Path(__file__).resolve().parents[1] / "chart"


def render(entry=None):
    command = ["helm", "template", "quarantine", str(CHART), "-n", "hermes-quarantine"]
    if entry is None:
        return subprocess.run(command, capture_output=True, text=True, check=False)
    with tempfile.TemporaryDirectory() as directory:
        values = pathlib.Path(directory) / "values.json"
        values.write_text(json.dumps({"egress": {"squidPodEgress": [entry]}}))
        return subprocess.run(command + ["-f", str(values)], capture_output=True, text=True, check=False)


def documents(rendered):
    return [segment.strip() for segment in re.split(r"(?m)^---\s*$", rendered) if segment.strip()]


class SquidPodEgressTests(unittest.TestCase):
    def test_opt_in_changes_only_one_policy_not_pod_templates(self):
        before = render()
        after = render({
            "namespace": "gateway-system",
            "podLabels": {
                "app.kubernetes.io/name": "nginx-gateway-proxy",
                "app.kubernetes.io/instance": "nginx-gateway-proxy",
                "app.kubernetes.io/controller": "main",
            },
            "port": 443,
        })
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)
        old = documents(before.stdout)
        new = documents(after.stdout)
        added = [d for d in new if "name: allow-squid-selected-pods\n" in d]
        self.assertEqual(len(added), 1)
        self.assertEqual([d for d in new if d not in added], old)
        policy = added[0]
        for value in (
            "kind: NetworkPolicy", "namespace: example-quarantine-gw",
            "app: egress-proxy", "kubernetes.io/metadata.name: \"gateway-system\"",
            "app.kubernetes.io/name: nginx-gateway-proxy",
            "app.kubernetes.io/instance: nginx-gateway-proxy",
            "app.kubernetes.io/controller: main", "port: 443",
        ):
            self.assertIn(value, policy)
        self.assertNotIn("ipBlock:", policy)
        self.assertEqual(policy.count("namespaceSelector:"), 1)
        self.assertEqual(policy.count("podSelector:"), 2)  # source and destination

    def test_missing_or_empty_selector_cannot_render(self):
        for entry in (
            {"namespace": "gateway-system", "port": 443},
            {"namespace": "gateway-system", "podLabels": {}, "port": 443},
            {"podLabels": {"app": "proxy"}, "port": 443},
            {"namespace": "gateway-system", "podLabels": {"app": "proxy"}},
        ):
            with self.subTest(entry=entry):
                result = render(entry)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("squidPodEgress", result.stderr)


if __name__ == "__main__":
    unittest.main()
