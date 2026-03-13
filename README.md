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
| **CA** | OpenBao via ExternalSecret + CronJob-Distribution |
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

1. **OpenBao Secrets:** CA-Keypair unter `apps/quarantine/<appName>/mitmproxy-ca` (Keys: `cert`, `key`). Falls Authentik: zusaetzlich Token unter `apps/quarantine/<appName>/authentik-token` (Key: `token`)
2. **Values-Datei** im Repo erstellen (`values-<appName>.yaml`)
3. **ArgoCD-App** erstellen (Source: dieses Repo, Helm mit `valueFiles: ["values-<appName>.yaml"]`, `ServerSideApply=true`, `ignoreDifferences` fuer HTTPRoute-Defaults)
4. Alles weitere passiert automatisch (Namespaces, Policies, Proxy, CA, Authentik-Setup)

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
| `authentik.openbaoPath` | auto | Default: `apps/quarantine/<appName>/authentik-token` |

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

## Abhaengigkeiten

- ClusterSecretStore `openbao` (ESO)
- Cilium Gateway API (cluster-gateway in gateway-system)
- Authentik (falls `authentik.enabled`)
- Longhorn (fuer mitmproxy PVC)
- ExternalDNS (fuer HTTPRoute-Annotations)
