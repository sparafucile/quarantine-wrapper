# PVC-independent mitmproxy rollout (opt-in)

`mitmproxy.ephemeralConfig: true` uses a bounded `emptyDir` for mitmproxy's
working configuration directory. The existing `mitmproxy-certs` PVC remains
rendered and retained, but is not mounted by the new Pod.

Prerequisites:

- `ca.enabled: true`: the existing CA Secret remains the authority. The init
  container checks both nonempty PEM inputs and copies them with restrictive
  permissions. This does not create or rotate the CA.
- Audit the old confdir before opting in. Preserve any manually installed
  `config.yaml`, custom keys, addons or other required files declaratively
  first. Generated DH parameters may be regenerated. Never print private keys.
- Do not expect persistent flow/config changes in the new confdir. `/data`
  already uses a separate emptyDir; this change does not add persistence.

The opt-in changes the Deployment to `RollingUpdate` with `maxSurge: 1` and
`maxUnavailable: 0`. TCP startup/readiness gates check the proxy listener.
A replacement Pod does not mount the old RWO PVC, so the old ready proxy can
remain available while the replacement starts on any eligible node. Scheduling
or CA initialization failure keeps the old ready replica in place. TCP readiness
is not a full upstream/authentication test; verify the actual proxy path after
rollout. Existing long-lived connections can still be interrupted on retirement.

Defaults remain unchanged for tenants without the opt-in (`Recreate`, RWO PVC).

## Activation order

1. Merge the chart capability first and verify its exact main revision.
2. Only then merge the tenant override. An old chart ignores unknown values;
   merging the consumer first could trigger another unsafe Recreate rollout.
3. Applications with automated sync may start reconciliation immediately after
   the tenant merge; do not promise a manual-only window. For a strictly manual
   handoff, control automated sync through a separately authorized owner change
   first. Verify Argo target manifests contain emptyDir, RollingUpdate and the
   intended stream threshold before any additional selective proxy sync.
4. Record old/new Pod UIDs and Service endpoint continuity during rollout.
   Require init success, startup/readiness, desired/updated/ready counts and
   real upstream probes. Do not run unrelated CA/Authentik/ExternalSecret hooks.
5. Verify the retained PVC still exists and has no new consumer. Do not prune it.

## Recovery and rollback

The streaming threshold and storage mode are independent. Keep a requested
`streamLargeBodies: "5m"` rollback while enabling safe storage/rollout behavior;
do not re-enable unbuffered streaming as part of storage recovery.

If the new Pod fails before readiness, inspect it and retain the old replica;
do not force-delete the healthy proxy. Reverting to PVC mode returns to Recreate
and may require a cross-node RWO handoff. That rollback is not zero-downtime:
preflight attachment/node placement and coordinate it explicitly. Never remove
VolumeAttachments or force-detach a volume still used by a running Pod.
