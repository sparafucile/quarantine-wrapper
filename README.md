# Quarantine-Wrapper

Generisches Helm Chart zum Erstellen isolierter Quarantine-Umgebungen fuer beliebige ArgoCD-Apps. Jede Instanz bekommt eigene Namespaces, vollstaendige NetworkPolicy-Isolation, einen dedizierten HTTP/HTTPS-Proxy-Stack und optionale Authentik-SSO-Integration.

## Overview

| Property | Value |
|----------|-------|
| **Chart** | quarantine-wrapper 1.6.1 |
| **Type** | Infra-Chart (kein bjw-s) |
| **Namespaces** | `<appName>-quarantine` + `<appName>-quarantine-gw` |
| **Proxy-Kette** | App -> mitmproxy (:8080) -> Squid (:3128) -> Internet |
| **Isolation** | NetworkPolicy + CiliumNetworkPolicy (default-deny) |
| **CA** | Auto-generiert via OpenBao K8s Auth + ExternalSecret + CronJob-Distribution |
| **mitmweb PW** | Auto-generiert via OpenBao, als `web_password` an mitmweb uebergeben |
| **Auth** | Authentik Proxy-Provider (PostSync-Job, auto-discovery) |

## Weiterführende Dokumentation

| Dokument | Inhalt |
|----------|--------|
| [docs/VALUES.md](docs/VALUES.md) | Vollstaendige Values-Referenz (alle Parameter mit Defaults und Beschreibung) |
| [docs/NETWORK-POLICIES.md](docs/NETWORK-POLICIES.md) | NetworkPolicy-Konzept (App-NS, Gateway-NS, CiliumNetworkPolicies) |
| [docs/LESSONS.md](docs/LESSONS.md) | Lessons Learned nach Version (v1.4.x – v1.6.1) |
| [BACKLOG.md](BACKLOG.md) | v2-Roadmap (Kyverno-Injection, app-agnostisch) + archiviertes App-Wissen |

## Architektur

```
+---------------------------------------------------------+
|  <appName>-quarantine (Namespace)                        |
|  +----------+  +----------+  +----------+               |
|  | App Pod  |  | App Pod  |  | hello-   | (optional)    |
|  +----+-----+  +----+-----+  | world    |               |
|       | Pod-zu-Pod   |        +----------+               |
|       +------+-------+                                   |
|              | Egress nur zu Proxy                        |
+--------------+-------------------------------------------+
|              v                                           |
|  <appName>-quarantine-gw (Namespace)                     |
|  +--------------+     +--------------+                   |
|  | mitmproxy    |---->| Squid Proxy  |  (Domain-Filter)  |
|  | :8080/:8081  |     | :3128        |                   |
|  | (upstream)   |     +------+-------+                   |
|  +--------------+            |                           |
|       |                      v                           |
|   mitmweb UI            Internet                         |
+---------------------------------------------------------+
```

**Proxy-Kette:** App-Pods nutzen mitmproxy als HTTP(S)-Proxy. mitmproxy laeuft im `upstream`-Modus und leitet allen Traffic an Squid weiter. Squid filtert nach Domain-Whitelist und leitet erlaubten Traffic ins Internet. Dadurch sind ALLE Requests (auch von Squid abgelehnte) in mitmweb sichtbar. Nur Squid hat Internet-Egress — mitmproxy kann das Internet nicht direkt erreichen.

## Deployment

Jede Quarantine-Instanz wird als eigene ArgoCD-App deployed:

```bash
# Helm Template testen
helm template <appName> . -f values-<appName>.yaml

# Lint
helm lint . -f values-<appName>.yaml
```

### Voraussetzungen fuer neue Instanzen

1. **Values-Datei** im Repo erstellen (`values-<appName>.yaml`)
2. **ArgoCD-App** erstellen (Source: dieses Repo, Helm mit `valueFiles: ["values-<appName>.yaml"]`, `ServerSideApply=true`, `ignoreDifferences` fuer HTTPRoute-Defaults)
3. Alles weitere passiert **vollautomatisch** beim ersten Sync:
   - Namespaces, Policies, Proxy, CA-Generierung, CA-Distribution, Authentik-Setup

**CA-Keypair + mitmweb-Passwort:** Werden automatisch beim ersten ArgoCD-Sync durch einen Sync-Hook Job (Wave -5) generiert und in OpenBao gespeichert. Pfade: `apps/quarantine/<appName>/mitmproxy-ca` (CA) und `apps/quarantine/<appName>/mitmweb-password` (Passwort). Manuelle Secret-Erstellung ist NICHT noetig.

**Authentik-Token:** Falls `authentik.enabled`: Der gemeinsame Token liegt unter `infra/authentik/api-token` (wird einmal zentral angelegt, nicht pro App).

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

## Minimalbeispiel (ohne Authentik)

```yaml
appName: default
services: []
mitmproxy:
  enabled: true
  authentik:
    enabled: false
ca:
  enabled: true
helloWorld:
  enabled: true
authentik:
  enabled: false
cilium:
  l7Visibility: false
```

## Minimalbeispiel (mit Authentik)

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
```

## Templates

| Template | Ressourcen |
|----------|-----------|
| `_helpers.tpl` | Namespace-Helpers, Label-Helpers, Hostname-Defaults, Proxy-Env |
| `namespaces.yaml` | 2 Namespaces |
| `networkpolicies-quarantine.yaml` | 7 NetworkPolicies |
| `networkpolicies-gateway.yaml` | 7-9 NetworkPolicies (je nach authentik.enabled) |
| `cilium-policies.yaml` | 3-5 CiliumNetworkPolicies |
| `squid.yaml` | ConfigMap, Deployment, Service |
| `mitmproxy.yaml` | PVC, Deployment, Service |
| `openbao-setup.yaml` | SA, ConfigMap (Python-Script), Sync-Hook Job (CA + mitmweb-PW auto-gen, Wave -5) |
| `external-secret.yaml` | ExternalSecret(s) (CA, mitmweb-PW, Authentik-Token) |
| `mitmproxy-ca-distribution.yaml` | SA, RBAC, Script-CM, CronJob, PostSync-Job |
| `httproutes.yaml` | HTTPRoutes (dynamisch aus services[]) |
| `reference-grants.yaml` | ReferenceGrants (Gateway + opt. Authentik) |
| `authentik-setup.yaml` | PostSync-Job (Proxy-Provider + Application + Outpost) |
| `hello-world.yaml` | Debug-Pod mit CA-Trust + Proxy-Env |
| `rbac.yaml` | Workload-RBAC (read-only) |

## Sync-Wave Ordering

| Wave | Ressourcen | Grund |
|------|-----------|-------|
| -10 | Namespaces | Muessen existieren bevor Ressourcen darin deployed werden |
| -5 | OpenBao-Setup (SA, ConfigMap, Job) | CA + mitmweb-PW muessen in OpenBao existieren bevor ExternalSecrets syncen |
| 0 | Alles andere (Default) | NetworkPolicies, Deployments, Services, ExternalSecrets |

Der `openbao-ca-setup` Job (Wave -5) ist ein ArgoCD Sync-Hook (`argocd.argoproj.io/hook: Sync`). Er laeuft bei jedem Sync, prueft ob CA-Keypair und mitmweb-Passwort bereits existieren und erstellt sie nur bei Bedarf. `hook-delete-policy: BeforeHookCreation` sorgt dafuer, dass alte Jobs vor dem naechsten Sync geloescht werden.

**Achtung beim Loeschen:** Falls eine App geloescht wird waehrend der Hook-Job laeuft, kann die Loeschung blockiert werden (Finalizer haengt). Fix: Job manuell loeschen mit `kubectl delete job openbao-ca-setup -n <appName>-quarantine-gw`.

## Abhaengigkeiten

- ClusterSecretStore `openbao` (ESO)
- Cilium Gateway API (cluster-gateway in gateway-system)
- Authentik (falls `authentik.enabled`)
- Longhorn (fuer mitmproxy PVC)
- ExternalDNS (fuer HTTPRoute-Annotations)

## Roadmap: v2 (app-agnostisch mit Kyverno)

Der Wrapper wird zu einem rein infrastrukturellen Chart umgebaut. Apps werden als eigenstaendige Helm Charts in den vom Wrapper kontrollierten Namespace deployed. Kyverno injiziert automatisch Proxy-Env-Vars, CA-Trust und Volumes — die App braucht keine Quarantine-Kenntnis. Dasselbe Chart funktioniert in einem normalen Namespace ohne Aenderung. Details im [BACKLOG.md](BACKLOG.md).
