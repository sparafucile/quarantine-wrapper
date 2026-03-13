# Quarantine-Wrapper

Generisches Helm Chart zum Erstellen isolierter Quarantine-Umgebungen fuer beliebige ArgoCD-Apps. Jede Instanz bekommt eigene Namespaces, vollstaendige NetworkPolicy-Isolation, einen dedizierten HTTP/HTTPS-Proxy-Stack und optionale Authentik-SSO-Integration.

## Overview

| Property | Value |
|----------|-------|
| **Chart** | quarantine-wrapper 1.0.0 |
| **Type** | Infra-Chart (kein bjw-s) |
| **Namespaces** | `<appName>-quarantine` + `<appName>-quarantine-gw` |
| **Proxy** | Squid (:3128) + mitmproxy (:8080/:8081) |
| **Isolation** | NetworkPolicy + CiliumNetworkPolicy (default-deny) |
| **CA** | Auto-generiert via OpenBao K8s Auth + ExternalSecret + CronJob-Distribution |
| **Auth** | Authentik Proxy-Provider (PostSync-Job, auto-discovery) |
| **Default-App** | `quarantine-default` (HelloWorld + mitmweb, kein Authentik) |

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
|  +--------------+  +--------------+                      |
|  | Squid Proxy  |  | mitmproxy    |  <- CA aus OpenBao   |
|  | :3128        |  | :8080/:8081  |                      |
|  +------+-------+  +------+-------+                      |
+---------+------------------+-----------------------------+
          v                  v
      Internet           mitmweb UI (opt. Authentik SSO)
```

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

**CA-Keypair:** Wird automatisch beim ersten ArgoCD-Sync durch einen Sync-Hook Job generiert und in OpenBao gespeichert (`apps/quarantine/<appName>/mitmproxy-ca`). Manuelle Secret-Erstellung ist NICHT mehr noetig.

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

## Values-Referenz

### Pflicht

| Parameter | Beschreibung |
|-----------|-------------|
| `appName` | App-Identifier, steuert alle dynamischen Namen |

### Services (Ingress)

```yaml
services:
  - name: web            # K8s Service-Name (muss dem tatsaechlichen K8s Service matchen)
    port: 8080           # Service-Port
    hostname: ...        # Externer Hostname fuer HTTPRoute + ExternalDNS
    authentik:
      enabled: true      # Authentik SSO fuer diesen Service
      skipPathRegex: ""  # API-Bypass Pattern (z.B. "^/api/")
```

Fuer jeden Service wird automatisch generiert: HTTPRoute, NetworkPolicy (Ingress-Port), CiliumNetworkPolicy (fromEntities: ingress). ACHTUNG: Wenn kein tatsaechlicher K8s Service mit diesem Namen existiert, wird die HTTPRoute Degraded (harmlos, aber ArgoCD zeigt Fehler).

### Authentik

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `authentik.enabled` | `true` | Authentik SSO global |
| `authentik.namespace` | `authentik` | Authentik Namespace |
| `authentik.outpostPk` | `1` | Fallback Outpost PK (Auto-Discovery aktiv) |
| `authentik.openbaoPath` | auto | Default: `infra/authentik/api-token` (shared) |

Wenn `authentik.enabled`: PostSync-Job erstellt automatisch Proxy-Provider, Applications und updated den Embedded Outpost. Flows (authorization + invalidation) werden auto-discovered via `/api/v3/flows/instances/`. Der Embedded Outpost wird ueber `/api/v3/outposts/instances/` gesucht (`type=proxy`).

### Proxy

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `squid.port` | `3128` | Squid Proxy Port |
| `mitmproxy.enabled` | `true` | mitmproxy TLS-Interception |
| `mitmproxy.proxyPort` | `8080` | mitmproxy Proxy Port |
| `mitmproxy.webPort` | `8081` | mitmweb UI Port |
| `mitmproxy.hostname` | auto | Default: `p-mitmweb-<appName>-k8s.sparafucile.net` |
| `mitmproxy.storageClass` | `longhorn` | PVC StorageClass |

### CA-Zertifikat

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `ca.enabled` | `true` | CA-Distribution aktivieren |
| `ca.openbaoPath` | auto | Default: `apps/quarantine/<appName>/mitmproxy-ca` |
| `ca.secretName` | `mitmproxy-ca` | K8s Secret Name |

### Hello-World Debug-Pod

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `helloWorld.enabled` | `false` | Debug-Pod aktivieren |
| `helloWorld.port` | `8080` | HTTP Port |
| `helloWorld.hostname` | auto | Default: `p-<appName>-hello-k8s.sparafucile.net` |

### Netzwerk

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `network.lanCIDR` | `192.168.4.0/24` | LAN-Subnetz |
| `network.podCIDR` | `10.244.0.0/16` | Cilium Pod-CIDR |
| `network.serviceCIDR` | `10.32.0.0/12` | K8s Service-CIDR |
| `network.coreDNSClusterIP` | `10.32.0.10` | CoreDNS ClusterIP |

## NetworkPolicy-Konzept

### App-Namespace (`<appName>-quarantine`)

- **default-deny** (Ingress + Egress)
- **allow-intra-namespace** (Pod-zu-Pod)
- **allow-dns** (CoreDNS)
- **allow-egress-to-proxy** (Squid + mitmproxy im gw-Namespace)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-lan-ingress** (LAN + kube-system + gateway-system, dynamische Ports)

### Gateway-Namespace (`<appName>-quarantine-gw`)

- **default-deny** (Ingress + Egress)
- **allow-ingress-from-quarantine** (App-Pods auf Proxy-Ports)
- **allow-mitmweb-ui** (LAN + Gateway auf Web-UI)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-dns** (CoreDNS)
- **allow-ca-distributor-egress** (K8s API Defense-in-Depth)
- **allow-internet-egress** (Internet minus LAN/Pod/Service-CIDR)
- **allow-authentik-egress** (wenn authentik.enabled: PostSync-Job zu Authentik)

### CiliumNetworkPolicies (KRITISCH)

K8s NetworkPolicies erkennen Cilium-Identitaeten nicht. Daher zusaetzlich:

- **allow-gateway-envoy-ingress** (fromEntities: host, ingress, kube-apiserver) — Pflicht fuer Gateway API
- **quarantine-l7-visibility** (Hubble HTTP-Monitoring, nur wenn `cilium.l7Visibility: true`)
- **allow-ca-distributor-apiserver** (toEntities: kube-apiserver — nach DNAT)
- **allow-authentik-setup-egress** (toCIDR: Service-CIDR + toEndpoints — fuer PostSync-Job)

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
| `openbao-setup.yaml` | SA, ConfigMap (Python-Script), Sync-Hook Job (CA auto-gen, Wave -5) |
| `external-secret.yaml` | ExternalSecret(s) (CA + opt. Authentik-Token) |
| `mitmproxy-ca-distribution.yaml` | SA, RBAC, Script-CM, CronJob, PostSync-Job |
| `httproutes.yaml` | HTTPRoutes (dynamisch aus services[]) |
| `reference-grants.yaml` | ReferenceGrants (Gateway + opt. Authentik) |
| `authentik-setup.yaml` | PostSync-Job (Proxy-Provider + Application + Outpost) |
| `hello-world.yaml` | Debug-Pod mit CA-Trust + Proxy-Env |
| `rbac.yaml` | Workload-RBAC (read-only) |

## Lessons Learned (Session 198)

### Cilium pre-DNAT: toCIDR statt toEndpoints fuer Service-Traffic

**Problem:** `toEndpoints` mit `matchLabels: io.kubernetes.pod.namespace` funktioniert NICHT fuer Traffic zu Service-ClusterIPs, wenn kube-proxy das DNAT macht. Cilium evaluiert Policies VOR dem kube-proxy DNAT — die ClusterIP hat keine Pod-Identity.

**Fix:** `toCIDR` mit Service-CIDR (`10.32.0.0/12`) fuer pre-DNAT-Matching verwenden, `toEndpoints` als Fallback fuer direkten Pod-zu-Pod-Traffic behalten. Siehe `allow-authentik-setup-egress` in `cilium-policies.yaml`.

**Merke:** `toEntities: kube-apiserver` funktioniert (Cilium kennt die Identity), aber `toEndpoints` funktioniert NICHT fuer beliebige Services via ClusterIP bei aktivem kube-proxy.

### Authentik API: Pflichtfelder fuer Provider-Erstellung

POST `/api/v3/providers/proxy/` erfordert zwingend `authorization_flow` und `invalidation_flow` (UUIDs). Das Script discovered diese automatisch via `/api/v3/flows/instances/?ordering=slug`.

### Authentik Embedded Outpost: kein fester PK

Der Embedded Outpost hat keinen vorhersagbaren Primary Key. Das Script sucht ihn via `/api/v3/outposts/instances/` und filtert nach `type=proxy`.

### OpenBao: intern nur HTTP

OpenBao ist cluster-intern nur via HTTP erreichbar (`http://openbao.openbao.svc.p-k8s-cluster.local:8200`). HTTPS verursacht SSL record layer failure.

### ArgoCD PostSync-Hooks: Sync-Phase-Ressourcen werden VORHER deployed

Neue Ressourcen (z.B. CiliumNetworkPolicies) die als regulaere Sync-Ressourcen (NICHT als Hook) definiert sind, werden in der Sync-Phase deployed — BEVOR PostSync-Hooks laufen. Das loest das Chicken-and-Egg-Problem: CNP fuer den PostSync-Job muss eine regulaere Ressource sein, KEIN Hook.

### OutOfSync bei ExternalSecrets und HTTPRoutes (kosmetisch)

ServerSideApply erzeugt Diffs bei ExternalSecrets (ESO-Webhook ergaenzt Defaults) und HTTPRoutes (API-Server ergaenzt group/kind/weight). `ignoreDifferences` fuer HTTPRoutes ist konfiguriert, ExternalSecret-Diffs sind harmlos (Health: Healthy).

## Sync-Wave Ordering

| Wave | Ressourcen | Grund |
|------|-----------|-------|
| -10 | Namespaces | Muessen existieren bevor Ressourcen darin deployed werden |
| -5 | OpenBao-Setup (SA, ConfigMap, Job) | CA muss in OpenBao existieren bevor ExternalSecret synct |
| 0 | Alles andere (Default) | NetworkPolicies, Deployments, Services, ExternalSecrets |

Der `openbao-ca-setup` Job (Wave -5) ist ein ArgoCD Sync-Hook (`argocd.argoproj.io/hook: Sync`). Er laeuft bei jedem Sync, prueft ob das CA-Keypair bereits existiert und erstellt es nur bei Bedarf. `hook-delete-policy: BeforeHookCreation` sorgt dafuer, dass alte Jobs vor dem naechsten Sync geloescht werden.

**Achtung beim Loeschen:** Falls eine App geloescht wird waehrend der Hook-Job laeuft, kann die Loeschung blockiert werden (Finalizer haengt). Fix: Job manuell loeschen mit `kubectl delete job openbao-ca-setup -n <appName>-quarantine-gw`.

## Abhaengigkeiten

- ClusterSecretStore `openbao` (ESO)
- Cilium Gateway API (cluster-gateway in gateway-system)
- Authentik (falls `authentik.enabled`)
- Longhorn (fuer mitmproxy PVC)
- ExternalDNS (fuer HTTPRoute-Annotations)
