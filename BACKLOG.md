# Backlog — quarantine-wrapper

## v2.0: App-agnostischer Wrapper mit Kyverno-Injection

**Status:** Konzept erstellt (2026-03-16), Umsetzung steht aus.

**Konzeptdokument:** Siehe `quarantine-wrapper-v2-konzept.md` im Claude-Workspace.

### v2-Aufgaben

- [ ] Kyverno als ArgoCD-App im Cluster installieren
- [ ] `kyverno-policy.yaml` Template erstellen (ClusterPolicy mit apiCall-Context)
- [ ] NetworkPolicies auf `podSelector: {}` umstellen
- [ ] Namespace-Annotations fuer Proxy-URL setzen (Kyverno liest via apiCall)
- [ ] `services[]` entfernen (App bringt eigene HTTPRoutes mit)
- [ ] OpenClaw als eigenstaendiges Helm Chart extrahieren (eigenes Gitea-Repo `k8s-apps/openclaw`)
- [ ] Wrapper v2 deployen + OpenClaw separat in `quarantine-showcase` installieren
- [ ] ArgoCD `ignoreDifferences` fuer Kyverno-injizierte Felder dokumentieren
- [ ] OpenBao-Secret-Schema auf `apps/quarantine/<namespace>/<appName>/` umstellen (mehrere Instanzen derselben App moeglich)

### Naming-Harmonisierung

- [ ] Einheitliches Namespace-Schema festlegen: `quarantine-<name>` oder `<name>-quarantine` oder frei via `appName`
- [ ] GW-Namespace: immer `<appName>-gw` (relativ zum App-NS)
- [ ] Alle Referenzen im Repo anpassen

## Archiviertes App-spezifisches Wissen

Die folgenden Informationen stammen aus entfernten app-spezifischen Dateien und dienen als Referenz fuer das kuenftige eigenstaendige OpenClaw-Chart.

### OpenClaw merge-config.py (Smart Merge)

**Zweck:** Selektiver Merge zwischen GitOps-kontrollierter ConfigMap und Runtime-modifizierter `openclaw.json`.

**GitOps-kontrollierte Keys** (werden aus ConfigMap ueberschrieben):
- `models` (Provider-Konfiguration)
- `gateway.port`, `gateway.bind`, `gateway.mode`, `gateway.controlUi`
- `agents.defaults.model`

**Runtime-Keys** (bleiben erhalten):
- `gateway.auth` (Telegram/WhatsApp Auth-Tokens)
- `channels` (Channel-Konfigurationen)
- `devices` (Device-Pairings)
- `meta` (Runtime-Metadaten)
- `commands` (Custom Commands)

**Ablauf:** Bei Erstinstallation: volle Kopie. Danach: Backup als `.pre-merge`, nur GitOps-Keys ueberschreiben.

### OpenClaw initContainer-Pattern

1. **merge-config** (python:3.12-slim): Smart-Merge ConfigMap → PVC
2. **trust-ca** (alpine:3.21): mitmproxy-CA in Trust-Bundle
3. **install-tools** (alpine:3.21): busybox-Symlinks fuer vi, less, grep, wget etc. nach emptyDir
4. **install-nano** (openclaw-image, runAsUser:0): apt install nano, Binary nach emptyDir

Volume-Layout: `cli-tools` (emptyDir) gemountet als `/usr/local/tools` readonly im Haupt-Container.

### OpenClaw Deployment-Spezifika

- **Strategy: Recreate** (wegen RWO-PVC auf Longhorn)
- **securityContext:** runAsUser/runAsGroup/fsGroup: 1000
- **Probes:** `/healthz` (liveness, 30s initial, 60s period), `/readyz` (readiness, 15s initial, 30s period)
- **Env:** `GEMINI_API_KEY` aus Secret, `OPENCLAW_STATE_DIR`, `OPENCLAW_CONFIG_PATH`, erweiterter `PATH` mit `/usr/local/tools`
- **Command:** `node openclaw.mjs gateway --allow-unconfigured`

### OpenClaw Values-Referenz (ehemals in values.yaml)

```yaml
openclaw:
  enabled: false
  image:
    repository: ghcr.io/openclaw/openclaw
    tag: latest
  gatewayPort: 18789
  model: "google/gemini-2.5-flash"
  storageClass: longhorn
  storageSize: 5Gi
  gemini:
    enabled: true
    secretName: openclaw-gemini-key
    openbaoPath: "infra/google-ai"    # oder per-instance
  resources:
    requests: { memory: "512Mi", cpu: "200m" }
    limits: { memory: "2Gi", cpu: "2000m" }
```

### Squid-Whitelist fuer OpenClaw (Referenz)

```yaml
egress:
  squidAllowedDomains:
    - generativelanguage.googleapis.com    # Google Gemini API
    - api.telegram.org                     # Telegram Bot API
    - deb.debian.org                       # Debian Packages (fuer apt install nano)
    - security.debian.org                  # Debian Security Updates
    - github.com                           # GitHub
    - openclaw.ai                          # OpenClaw Updates/Docs
```

### ExternalSecret fuer Gemini API-Key

OpenBao-Pfad: `infra/google-ai`, Property: `api-key`. Target-Secret: `openclaw-gemini-key`. Sollte im eigenstaendigen OpenClaw-Chart mit eigenem ExternalSecret reproduziert werden.

### OpenBao-Secret-Schema (NEU fuer v2)

Aktuell: `apps/quarantine/<appName>/<secret>` (z.B. `apps/quarantine/showcase/mitmproxy-ca`)

Geplant fuer v2: `apps/quarantine/<namespace>/<secret>` — damit koennen mehrere Instanzen derselben App mit unterschiedlichen Secrets laufen.

Alternativ hierarchisch: `apps/quarantine/<namespace>/<appName>/<secret>` fuer volle Flexibilitaet.
