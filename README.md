# Quarantine-Wrapper

Generisches Helm Chart zum Erstellen isolierter Quarantine-Umgebungen fuer beliebige ArgoCD-Apps. Jede Instanz bekommt eigene Namespaces, vollstaendige NetworkPolicy-Isolation, einen dedizierten HTTP/HTTPS-Proxy-Stack, ein Web-basiertes ControlCenter und optionale Authentik-SSO-Integration.

## Overview

| Property | Value |
|----------|-------|
| **Chart** | quarantine-wrapper (`chart/`) |
| **Type** | Infra-Chart (kein bjw-s) |
| **Namespaces** | `<appName>-quarantine` + `<appName>-quarantine-gw` |
| **Proxy-Kette** | App -> mitmproxy (:8080) -> Squid (:3128) -> Internet |
| **Isolation** | NetworkPolicy + CiliumNetworkPolicy (default-deny) |
| **CA** | Auto-generiert via OpenBao K8s Auth + ExternalSecret + CronJob-Distribution |
| **mitmweb PW** | Auto-generiert via OpenBao, als `web_password` an mitmweb uebergeben |
| **Auth** | Authentik Proxy-Provider (PostSync-Job, auto-discovery in App- UND GW-Namespace) |
| **ControlCenter** | Web-UI fuer Whitelist, Denied-Logs, Traffic, Pods, Health (optional) |

## Weiterfuehrende Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [docs/VALUES.md](docs/VALUES.md) | Vollstaendige Values-Referenz (alle Parameter mit Defaults und Beschreibung) |
| [docs/NETWORK-POLICIES.md](docs/NETWORK-POLICIES.md) | NetworkPolicy-Konzept (App-NS, Gateway-NS, CiliumNetworkPolicies) |
| [docs/LESSONS.md](docs/LESSONS.md) | Lessons Learned nach Version (v1.4.x – v1.6.1) |
| [docs/CONTROLCENTER-BACKLOG.md](docs/CONTROLCENTER-BACKLOG.md) | ControlCenter-spezifisches Backlog |

## Architektur

```
+--------------------------------------------------------------+
|  <appName>-quarantine (Namespace)                             |
|  +----------+  +----------+  +----------+                    |
|  | App Pod  |  | App Pod  |  | hello-   | (optional)         |
|  +----+-----+  +----+-----+  | world    |                    |
|       | Pod-zu-Pod   |        +----------+                    |
|       +------+-------+                                        |
|              | Egress nur zu Proxy                             |
+--------------+------------------------------------------------+
|              v                                                |
|  <appName>-quarantine-gw (Namespace)                          |
|  +--------------+     +--------------+   +----------------+  |
|  | mitmproxy    |---->| Squid Proxy  |   | ControlCenter  |  |
|  | :8080 proxy  |     | :3128 filter |   | :8080 web-ui   |  |
|  | :8081 web-ui |     +------+-------+   | (optional)     |  |
|  | (upstream)   |            |           +----------------+  |
|  +--------------+            v                                |
|                         Internet                              |
+--------------------------------------------------------------+
                              ^
                              | Nur Squid hat Internet-Egress
```

**Proxy-Kette:** App-Pods nutzen mitmproxy als HTTP(S)-Proxy. mitmproxy laeuft im `upstream`-Modus und leitet allen Traffic an Squid weiter. Squid filtert nach Domain-Whitelist und leitet erlaubten Traffic ins Internet. Dadurch sind ALLE Requests (auch von Squid abgelehnte) in mitmweb sichtbar. Nur Squid hat Internet-Egress — mitmproxy kann das Internet nicht direkt erreichen.

**ControlCenter (optional):** Web-UI im GW-Namespace zur Verwaltung der Quarantine-Umgebung. Bietet: Squid-Whitelist-Management mit ArgoCD-Sync-Feedback, Denied-Log-Viewer mit persistentem Cache, mitmproxy Traffic-Inspektion mit Deep-Links, Pod-Status mit Headlamp-Links, NetworkPolicy-Uebersicht, Proxy-Chain Health-Check, Bypass-Modus und Paketmanager-Vorlagen (npm/pip/apt/Docker/GitHub). Quellcode in `controlcenter/`, Image wird via Jenkins als `quarantine-controlcenter` nach Harbor gepusht.

## Deployment

Jede Quarantine-Instanz wird als eigene ArgoCD-App deployed:

```bash
# Helm Template testen
helm template <appName> chart --set appName=<appName>

# Lint
helm lint chart --set appName=<appName>
```

### Voraussetzungen fuer neue Instanzen

1. **ArgoCD-App** erstellen: Source: dieses Repo, Path: `chart`, Helm-Parameter `appName=<name>` setzen, `ServerSideApply=true`, `ignoreDifferences` fuer HTTPRoute-Defaults
2. Alles weitere passiert **vollautomatisch** beim ersten Sync:
   - Namespaces, Policies, Proxy, CA-Generierung, CA-Distribution, Authentik-Setup

**CA-Keypair + mitmweb-Passwort:** Werden automatisch beim ersten ArgoCD-Sync durch einen Sync-Hook Job (Wave -5) generiert und in OpenBao gespeichert. Manuelle Secret-Erstellung ist NICHT noetig.

**Authentik-Token:** Falls `authentik.enabled`: Der gemeinsame Token liegt unter `infra/authentik/api-token` (wird einmal zentral angelegt, nicht pro App). Das Setup-Script entdeckt Services mit Label `quarantine.sparafucile.net/authentik: "true"` automatisch — in BEIDEN Namespaces (App + GW).

**Einmalige Cluster-Voraussetzungen** (bereits eingerichtet):
- OpenBao K8s Auth Role `quarantine-setup` (SA `openbao-setup`, alle Namespaces)
- OpenBao Policy `quarantine-setup-write` (write auf `secret/data/apps/quarantine/*`)
- ClusterSecretStore `openbao` (ESO)
- Shared Authentik Token unter `infra/authentik/api-token`

### ArgoCD-App-Konfiguration

```yaml
syncPolicy:
  automated:
    selfHeal: true
  syncOptions:
    - CreateNamespace=false
    - ServerSideApply=true
ignoreDifferences:
  - group: gateway.networking.k8s.io
    kind: HTTPRoute
    jsonPointers:
      - /spec/rules/0/backendRefs/0/group
      - /spec/rules/0/backendRefs/0/kind
      - /spec/rules/0/backendRefs/0/weight
```

## Minimalbeispiel (mit ControlCenter + Authentik)

```yaml
appName: myapp
services:
  - name: web
    port: 8080
    hostname: p-myapp-k8s.sparafucile.net
    authentik:
      enabled: true
mitmproxy:
  enabled: true
  authentik:
    enabled: true
authentik:
  enabled: true
controlcenter:
  enabled: true
```

## CI/CD (ControlCenter Image)

Das ControlCenter-Image wird via Jenkins Shared Library gebaut:

```groovy
// Jenkinsfile
@Library('k8s-apps-library') _
k8sAppPipeline(
    appname: 'quarantine-controlcenter',  // Harbor-Image-Name
    repoName: 'quarantine-wrapper',       // Gitea-Repo (Monorepo-Pattern)
    dockerpath: 'controlcenter',
    srcpaths: 'controlcenter/**,VERSION'
)
```

Die Pipeline baut das Image bei Aenderungen in `controlcenter/` oder `VERSION`, aktualisiert automatisch `chart/values.yaml` mit Image-Tag, Build-Nummer, Datum und Commit-Hash.

## Templates

| Template | Ressourcen |
|----------|-----------|
| `_helpers.tpl` | Namespace-Helpers, Label-Helpers, Hostname-Defaults, Proxy-Env |
| `namespaces.yaml` | 2 Namespaces |
| `networkpolicies-quarantine.yaml` | 7 NetworkPolicies |
| `networkpolicies-gateway.yaml` | 7-9 NetworkPolicies (je nach authentik/controlcenter.enabled) |
| `cilium-policies.yaml` | 3-6 CiliumNetworkPolicies |
| `squid.yaml` | ConfigMap, Deployment, Service |
| `mitmproxy.yaml` | PVC, Deployment, Service |
| `controlcenter.yaml` | SA, RBAC (beide NS), Deployment, Service (optional) |
| `openbao-setup.yaml` | SA, ConfigMap (Python-Script), Sync-Hook Job (CA + mitmweb-PW, Wave -5) |
| `external-secret.yaml` | ExternalSecret(s) (CA, mitmweb-PW, Authentik-Token, CC-Tokens) |
| `mitmproxy-ca-distribution.yaml` | SA, RBAC, Script-CM, CronJob, PostSync-Job |
| `httproutes.yaml` | HTTPRoutes (mitmweb, hello-world, controlcenter) |
| `reference-grants.yaml` | ReferenceGrants (Gateway + opt. Authentik) |
| `authentik-setup.yaml` | PostSync-Job (Service-Discovery in App+GW NS, Provider+App+Outpost) |
| `authentik-cleanup.yaml` | PreDelete-Job (Provider+App Cleanup) |
| `hello-world.yaml` | Debug-Pod mit CA-Trust + Proxy-Env (optional) |
| `kyverno-policy.yaml` | ClusterPolicy fuer Proxy-Env/CA-Injection (optional) |
| `rbac.yaml` | Workload-RBAC (read-only) |

## Sync-Wave Ordering

| Wave | Ressourcen | Grund |
|------|-----------|-------|
| -10 | Namespaces | Muessen existieren bevor Ressourcen darin deployed werden |
| -5 | OpenBao-Setup (SA, ConfigMap, Job) | CA + mitmweb-PW muessen in OpenBao existieren bevor ExternalSecrets syncen |
| 0 | Alles andere (Default) | NetworkPolicies, Deployments, Services, ExternalSecrets |

## Abhaengigkeiten

- ClusterSecretStore `openbao` (ESO)
- Cilium Gateway API (cluster-gateway in gateway-system)
- Authentik (falls `authentik.enabled`)
- Longhorn (fuer mitmproxy PVC)
- ExternalDNS (fuer HTTPRoute-Annotations)
- Kyverno (falls `kyverno.enabled`, fuer automatische Proxy-Env-Injection)
