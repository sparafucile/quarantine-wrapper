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
| **Auth** | Authentik Proxy-Provider (PostSync-Job) |

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
      Internet           mitmweb UI -> Authentik SSO
```

## Deployment

Jede Quarantine-Instanz wird als eigene ArgoCD-App deployed:

```bash
# Helm Template testen
helm template <appName> ./chart -f values-<appName>.yaml

# Lint
helm lint ./chart -f values-<appName>.yaml
```

## Minimalbeispiel

```yaml
appName: openclaw

services:
  - name: web
    port: 8080
    hostname: p-openclaw-k8s.sparafucile.net
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
  - name: web            # K8s Service-Name
    port: 8080           # Service-Port
    hostname: ...        # Externer Hostname fuer HTTPRoute
    authentik:
      enabled: true      # Authentik SSO fuer diesen Service
      skipPathRegex: ""  # API-Bypass Pattern
```

Fuer jeden Service wird automatisch generiert: HTTPRoute, NetworkPolicy (Ingress-Port), CiliumNetworkPolicy (fromEntities: ingress).

### Egress

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `egress.squidExtraDomains` | `[]` | Zusaetzliche Domains fuer Squid-ACL |
| `egress.extraEgressRules` | `[]` | Zusaetzliche K8s NetworkPolicy egress rules |

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

### App-Namespace

- **default-deny** (Ingress + Egress)
- **allow-intra-namespace** (Pod-zu-Pod)
- **allow-dns** (CoreDNS)
- **allow-egress-to-proxy** (Squid + mitmproxy im gw-Namespace)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-lan-ingress** (LAN + kube-system + gateway-system, dynamische Ports)

### Gateway-Namespace

- **default-deny** (Ingress + Egress)
- **allow-ingress-from-quarantine** (App-Pods auf Proxy-Ports)
- **allow-mitmweb-ui** (LAN + Gateway auf Web-UI)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-dns** (CoreDNS)
- **allow-ca-distributor-egress** (K8s API Defense-in-Depth)
- **allow-internet-egress** (Internet minus LAN/Pod/Service-CIDR)
- **allow-authentik-egress** (PostSync-Job zu Authentik)

### CiliumNetworkPolicies

- **allow-gateway-envoy-ingress** (fromEntities: host, ingress, kube-apiserver) - KRITISCH fuer Gateway API
- **quarantine-l7-visibility** (Hubble HTTP-Monitoring)
- **allow-ca-distributor-apiserver** (toEntities: kube-apiserver nach DNAT)

## Templates

| Template | Ressourcen |
|----------|-----------|
| `_helpers.tpl` | Namespace-Helpers, Label-Helpers, Hostname-Defaults, Proxy-Env |
| `namespaces.yaml` | 2 Namespaces |
| `networkpolicies-quarantine.yaml` | 7 NetworkPolicies |
| `networkpolicies-gateway.yaml` | 9 NetworkPolicies |
| `cilium-policies.yaml` | 4 CiliumNetworkPolicies |
| `squid.yaml` | ConfigMap, Deployment, Service |
| `mitmproxy.yaml` | PVC, Deployment, Service |
| `external-secret.yaml` | ExternalSecret (OpenBao CA) |
| `mitmproxy-ca-distribution.yaml` | SA, RBAC, Script-CM, CronJob, PostSync-Job |
| `httproutes.yaml` | HTTPRoutes (dynamisch aus services[]) |
| `reference-grants.yaml` | ReferenceGrants fuer Gateway |
| `authentik-setup.yaml` | PostSync-Job (Proxy-Provider + Application) |
| `hello-world.yaml` | Debug-Pod mit CA-Trust + Proxy-Env |
| `rbac.yaml` | Workload-RBAC (read-only) |

## Migration von quarantine-network

1. CA-Keypair in OpenBao unter neuem Pfad speichern: `apps/quarantine/<appName>/mitmproxy-ca`
2. Neue ArgoCD-App `quarantine-<appName>` erstellen
3. Alte `quarantine-network` App + Namespaces entfernen
4. Hello-World in neuem Namespace verifizieren

## Neue Quarantine-Umgebung erstellen

1. Values-Datei erstellen mit `appName` und `services[]`
2. CA-Keypair generieren und in OpenBao speichern
3. Authentik API-Token Secret erstellen (falls `authentik.enabled`)
4. ArgoCD-App erstellen die auf dieses Chart + Values zeigt
5. Sync + Verifizieren (NetworkPolicy, Proxy, CA, HTTPRoutes)

## Abhaengigkeiten

- ClusterSecretStore `openbao` (ESO)
- Cilium Gateway API (cluster-gateway in gateway-system)
- Authentik (falls `authentik.enabled`)
- Longhorn (fuer mitmproxy PVC)
