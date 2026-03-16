# Quarantine-Wrapper

Generisches Helm Chart zum Erstellen isolierter Quarantine-Umgebungen fuer beliebige ArgoCD-Apps. Jede Instanz bekommt eigene Namespaces, vollstaendige NetworkPolic-Isolation, einen dedizierten HTTP/HTTPS-Proxy-Stack und optionale Authentik-SSO-Integration.

## Overview

| Property | Value |
|--------------|----------|
| **Chart** | quarantine-wrapper 1.6.1 |
| **Type** | Infra-Chart (kein bjw-s) |
| **Namespaces** | `<appName>-quarantine` + `<appName>-quarantine-gw` |
| **Proxy-Kette** | App -> mitmproxy (:8080) -> Squid (:3128) -> Internet |
| **Isolation** | NetworkPolicy + CiliumNetworkPolicy (default-deny) |
| **CA** | Auto-generiert via OpenBao K8s Auth + ExternalSecret + CronJob-Distribution |
| **mitmweb PW** | Auto-generiert via OpenBao, als `web_password` an mitmweb uebergeben |
| **Auth** | Authentik Proxy-Provider (PostSync-Job, auto-discovery) |

## Templates

| Template | Resources |
|----------|-----------|
| `openclaw.yaml` | PVC, ConfigMap (openclaw.json + merge-config.py), Deployment (4 initContainers: merge-config, trust-ca, install-tools, install-nano), Service |

## Lessons Learned (Session 198)

### NODE_USE_ENV_PROXY fuer Node.js 24+ (v1.6.0)

**Problem:** Node.js 24+ mit undici/fetch ignoriert HTTP_PROXY/HTTPS_PROXY Environment-Variablen standardmaessig. In der Quarantine-Umgebung fuehrt das dazu, dass HTTPS-Requests direkt rausgehen und von der NetworkPolicy blockiert werden → Timeout.

**Fix:** `NODE_USE_ENV_PROXY=1` als Environment-Variable setzen. Ist im `proxyEnv` Helm-Helper enthalten und wird automatisch an alle Pods verteilt.

### Smart Merge fuer openclaw.json (v1.6.0)

**Problem:** OpenClaw modifiziert `openclaw.json` zur Laufzeit (auth tokens, channel configs, device pairings, model auto-migration). Ein blindes Ueberschreiben per ConfigMap bei Pod-Restart zerstoert diese Runtime-Daten.

**Fix:** initContainer `merge-config` (python:3.12-slim) fuehrt selektiven Merge durch: GitOps-kontrollierte Keys (models, gateway.port/bind/mode/controlUi, agents.defaults.model) werden aus ConfigMap ueberschrieben, Runtime-Keys (gateway.auth, channels, devices, meta, commands) bleiben erhalten. Bei Erstinstallation wird die volle ConfigMap kopiert. Backup als `openclaw.json.pre-merge` vor jedem Merge.

### CLI-Tools in Quarantine-Pods (v1.6.1)

**Problem:** Im OpenClaw-Container (non-root, UID 1000) kann weder `apt-get install` (braucht root) noch `apk add` (falsches Base-Image) ausgefuehrt werden.

**Fix:** Zwei initContainers: (1) `install-tools` (Alpine) kopiert busybox und erstellt Symlinks fuer vi, less, grep, sed, awk, wget etc. (2) `install-nano` (OpenClaw-Image mit `securityContext.runAsUser: 0`) installiert nano via apt-get und kopiert das Binary. Beide schreiben in ein emptyDir-Volume, das als `/usr/local/tools` readonly in den Haupt-Container gemountet wird. Braucht `deb.debian.org` + `security.debian.org` in der Squid-Whitelist.

### Recreate-Strategie bei RWO-PVCs (v1.6.1)

**Problem:** ReadWriteOnce-PVCs koennen nur auf einem Node gemountet werden. Mit RollingUpdate-Strategie startet K8s den neuen Pod BEVOR der alte terminiert wird. Landet der neue Pod auf einem anderen Node, haengt er ewig in `Init:0/x` weil die PVC nicht gemountet werden kann.

**Fix:** `strategy.type: Recreate` im Deployment-Spec. K8s terminiert erst den alten Pod, dann startet es den neuen — PVC ist immer frei.

### ServerSideApply Array-Merge bei initContainern (v1.6.1)

**Problem:** SSA mergt Arrays nach `name`-Feld statt sie zu ersetzen. Beim Umbenennen eines initContainers (z.B. `copy-config` → `merge-config`) bleibt der alte bestehen, das Deployment hat dann mehr initContainers als erwartet.

**Fix:** Einmalig mit `Replace=true` ueber ArgoCD syncen: `POST /api/v1/applications/<app>/sync` mit `syncOptions: {items: ["Replace=true"]}` und gezieltem `resources`-Filter fuer das betroffene Deployment.

### Cilium Stale Endpoint nach Node-Wechsel (v1.6.1)

**Problem:** Wenn ein Pod durch Recreate-Strategie auf einen anderen Node wandert, kann Cilium's Envoy den alten Endpoint gecacht halten. Ergebnis: "upstream connect error / Connection timed out" (503) obwohl der Pod Ready ist und kubelet Health-Checks bestehen.

**Fix:** Pod loeschen (erneuter Restart), damit Cilium den Endpoint frisch programmiert. Tritt besonders nach erstmaliger Umstellung auf Recreate-Strategie auf.

### OpenClaw (App-spezifisch)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `openclaw.enabled` | `false` | OpenClaw Deployment aktivieren |
| `openclaw.image.repository` | `ghcr.io/openclaw/openclaw` | Container-Image |
| `openclaw.image.tag` | `latest` | Image-Tag |
| `openclaw.gatewayPort` | `18789` | Gateway-Port |
| `openclaw.model` | `google/gemini-2.5-flash` | Primaeres AI-Modell |
| `openclaw.storageClass` | `longhorn` | PVC StorageClass |
| `openclaw.storageSize` | `5Gi` | PVC-Groesse |
| `openclaw.gemini.enabled` | `true` | Gemini Provider aktivieren |
| `openclaw.gemini.secretName` | `openclaw-gemini-key` | K8s Secret fuer Gemini API Key |
