# Values-Referenz

Vollstaendige Parameter-Dokumentation fuer den quarantine-wrapper Helm Chart (`chart/`).

## Pflicht

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `appName` | `"example"` | App-Identifier, steuert alle dynamischen Namen. MUSS in ArgoCD ueberschrieben werden! |
| `clusterDNS` | `"p-k8s-cluster.local"` | Cluster-DNS-Domain (kubeadm --service-dns-domain) |

## Kyverno (v2 Injection)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `kyverno.enabled` | `true` | ClusterPolicy fuer automatische Proxy-Env/CA-Injection in App-Pods |

Wenn aktiviert, werden Proxy-Env-Vars, CA-Trust-initContainer und Volumes automatisch in alle Pods des App-Namespace injiziert. Apps brauchen keine Quarantine-Kenntnis.

## Ingress-Ports (v2)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `ingressPorts` | `[]` | TCP-Ports die von Gateway/LAN/kube-system erreichbar sein sollen |

Erzeugt NetworkPolicy- und CiliumNetworkPolicy-Regeln fuer die angegebenen Ports. Apps deployen ihre eigenen Services und HTTPRoutes — der Wrapper oeffnet nur die Firewall.

```yaml
ingressPorts:
  - 8080   # z.B. App-HTTP-Port
```

## Services (Legacy v1 / vereinfacht)

```yaml
services:
  - name: web            # K8s Service-Name
    port: 8080           # Service-Port
    hostname: ...        # Externer Hostname fuer HTTPRoute + ExternalDNS
    authentik:
      enabled: true      # Authentik SSO fuer diesen Service
      skipPathRegex: ""  # API-Bypass Pattern (z.B. "^/api/v1/")
```

Fuer jeden Service wird generiert: HTTPRoute, NetworkPolicy (Ingress-Port), CiliumNetworkPolicy (fromEntities: ingress). Bei v2-Deployments mit Kyverno werden stattdessen `ingressPorts` + `authentik.externalApps` verwendet.

## Authentik

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `authentik.enabled` | `true` | Authentik SSO global aktivieren |
| `authentik.namespace` | `authentik` | Authentik K8s-Namespace |
| `authentik.apiTokenSecret` | `""` | K8s Secret Name mit API-Token (Default: `authentik-api-token`) |
| `authentik.openbaoPath` | auto | OpenBao-Pfad fuer API-Token (Default: `infra/authentik/api-token`) |
| `authentik.outpostPk` | `1` | Fallback Outpost PK (Auto-Discovery per API aktiv) |

Wenn `authentik.enabled`: PostSync-Job erstellt automatisch Proxy-Provider, Applications und updated den Embedded Outpost. **Service-Discovery scannt beide Namespaces** (App + GW) nach Services mit Label `quarantine.sparafucile.net/authentik: "true"` und Annotation `quarantine.sparafucile.net/external-host`. Flows (authorization + invalidation) werden auto-discovered.

### Authentik External Apps

```yaml
authentik:
  externalApps:
    - name: myapp                                   # Provider-Name (wird zu <appName>-<name>)
      hostname: p-myapp-k8s.sparafucile.net          # Externer Hostname
      service: myapp                                 # K8s Service-Name im App-Namespace
      port: 18789                                   # Service-Port
      skipPathRegex: "^/api/v1/"                    # API-Bypass Regex (optional, leer = kein Bypass)
```

`skipPathRegex` erlaubt es, bestimmte Pfade vom Authentik-Schutz auszunehmen (z.B. API-Endpunkte die eigene Auth haben). Leerer String oder Weglassen = alles geschuetzt.

## Egress / Squid-Whitelist

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `egress.squidAllowedDomains` | `[placeholder...]` | Domain-Whitelist fuer Squid (Default: Dummy-Domain, blockiert alles) |
| `egress.extraEgressRules` | `[]` | Zusaetzliche K8s NetworkPolicy egress rules |

**WICHTIG:** Der Default-Wert enthaelt eine Dummy-Domain (`placeholder.quarantine.internal`), sodass Squid standardmaessig ALLES blockiert. Eine leere Liste (`[]`) wuerde alles erlauben — das ist NICHT der Default. Subdomains werden automatisch eingeschlossen (`.example.com` matcht auch `sub.example.com`). Der Squid-Pod restartet automatisch bei Aenderungen (Checksum-Annotation).

## Proxy-Kette

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `squid.image.repository` | `ubuntu/squid` | Squid Container Image |
| `squid.image.tag` | `latest` | Squid Image Tag |
| `squid.port` | `3128` | Squid Proxy Port |
| `squid.resources` | 100m/256Mi - 500m/1Gi | CPU/Memory Requests/Limits |
| `mitmproxy.enabled` | `true` | mitmproxy TLS-Interception + upstream-Modus |
| `mitmproxy.image.repository` | `mitmproxy/mitmproxy` | mitmproxy Container Image |
| `mitmproxy.image.tag` | `latest` | mitmproxy Image Tag |
| `mitmproxy.proxyPort` | `8080` | mitmproxy Proxy Port |
| `mitmproxy.webPort` | `8081` | mitmweb UI Port |
| `mitmproxy.hostname` | auto | Default: `p-<appName>-mitmweb-k8s.<domain>` |
| `mitmproxy.openbaoPath` | auto | Default: `apps/<appName>-quarantine/mitmweb-password` |
| `mitmproxy.storageClass` | `longhorn` | PVC StorageClass |
| `mitmproxy.storageSize` | `100Mi` | PVC Groesse (Longhorn) |
| `mitmproxy.resources` | 100m/256Mi - 1000m/2Gi | CPU/Memory Requests/Limits |
| `mitmproxy.authentik.enabled` | `true` | mitmweb Web-UI hinter Authentik schuetzen |

Proxy-Verhalten:
- **`mitmproxy.enabled: true`** — Apps nutzen `mitmproxy:8080`. mitmproxy leitet im `upstream`-Modus an Squid weiter. Alle Requests in mitmweb sichtbar.
- **`mitmproxy.enabled: false`** — Apps nutzen `squid:3128` direkt. Keine TLS-Interception.

### Automatisch gesetzte Proxy-Env-Vars (via Kyverno oder proxyEnv-Helper)

| Variable | Wert | Beschreibung |
|----------|------|-------------|
| `HTTP_PROXY` / `http_proxy` | `http://mitmproxy.<gw-ns>:8080` (oder `squid:3128`) | HTTP-Proxy |
| `HTTPS_PROXY` / `https_proxy` | (gleich) | HTTPS-Proxy |
| `NO_PROXY` / `no_proxy` | `127.0.0.1,localhost,.<app-ns>.svc,.<gw-ns>.svc,<serviceCIDR>` | Proxy-Bypass |
| `NODE_USE_ENV_PROXY` | `1` | Pflicht fuer Node.js 24+ (undici/fetch) |
| `SSL_CERT_FILE` | `/etc/ssl/custom/ca-certificates.crt` | TLS CA-Trust |
| `REQUESTS_CA_BUNDLE` | `/etc/ssl/custom/ca-certificates.crt` | Python requests CA-Trust |
| `NODE_EXTRA_CA_CERTS` | `/etc/ssl/custom/ca-certificates.crt` | Node.js CA-Trust |

**Hinweis:** Diese Env-Vars werden nur im **App-Namespace** automatisch gesetzt (via Kyverno). Pods im **GW-Namespace** (z.B. ControlCenter) bekommen sie NICHT — dort muessen Proxy-Config und CA-Trust explizit im Deployment-Template gesetzt werden.

## CA-Zertifikat

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `ca.enabled` | `true` | CA-Generierung und -Distribution aktivieren |
| `ca.openbaoPath` | auto | Default: `apps/<appName>-quarantine/mitmproxy-ca` |
| `ca.secretName` | `mitmproxy-ca` | K8s Secret Name im GW-Namespace |
| `ca.distributorImage.repository` | `python` | Image fuer CA-Distribution CronJob |
| `ca.distributorImage.tag` | `"3.12-slim"` | Tag (Debian-basiert, hat openssl vorinstalliert) |
| `ca.initImage.repository` | `alpine` | Image fuer CA-Install initContainers |
| `ca.initImage.tag` | `"3.21"` | Alpine Tag |

## ControlCenter (Web-UI)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `controlcenter.enabled` | `false` | ControlCenter aktivieren |
| `controlcenter.image.repository` | Harbor Registry | CC Container Image |
| `controlcenter.image.tag` | `"1.0.14"` | CC Image Tag (von Jenkins Stage 2 gesetzt) |
| `controlcenter.port` | `8080` | CC HTTP Port |
| `controlcenter.hostname` | auto | Default: `p-<appName>-quarantine-cc-k8s.<domain>` |
| `controlcenter.resources` | 50m/64Mi - 500m/256Mi | CPU/Memory Requests/Limits |

Das CC bekommt automatisch: mitmproxy-CA (initContainer), `PROXY_URL` (expliziter Proxy-Zugang fuer Health-Check), `MITMWEB_URL` (fuer Deep-Links), `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` (CA-Trust), `MITMPROXY_PASSWORD` (fuer mitmweb API-Auth via `?token=`), sowie `BUILD_NUMBER`/`BUILD_DATE`/`BUILD_COMMIT` aus der `build:` Section.

## Build (Jenkins CI/CD)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `build.number` | `"dev"` | Jenkins Build-Nummer (von Stage 2 gesetzt) |
| `build.date` | `""` | Build-Datum UTC (von Stage 2 gesetzt) |
| `build.commit` | `""` | Git Short-Hash (von Stage 2 gesetzt) |

Werden im CC-Footer angezeigt: `v1.0.14 | Build #187 | 3468841 | 2026-03-19 11:43 UTC`

## Hello-World Debug-Pod

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `helloWorld.enabled` | `false` | Debug-Pod aktivieren |
| `helloWorld.image.repository` | `nginx` | Image |
| `helloWorld.image.tag` | `"1.27-alpine"` | Tag |
| `helloWorld.port` | `8080` | HTTP Port |
| `helloWorld.hostname` | auto | Default: `p-<appName>-hello-k8s.<domain>` (via Helper) |
| `helloWorld.resources` | 10m/32Mi - 100m/64Mi | CPU/Memory Requests/Limits |

Wenn `authentik.enabled`: Hello-World-Route wird ueber Authentik geschuetzt (Backend: `authentik-server:80` statt `hello-world:8080`).

## Gateway

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `gateway.name` | `cluster-gateway` | Cilium Gateway Name |
| `gateway.namespace` | `gateway-system` | Gateway Namespace |
| `gateway.sectionName` | `https-wildcard` | Gateway Listener Section |
| `gateway.domain` | `sparafucile.net` | Base-Domain fuer Hostname-Defaults |

## Netzwerk

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `network.lanCIDR` | `192.168.4.0/24` | LAN-Subnetz (erlaubt in Ingress-Policies) |
| `network.podCIDR` | `10.244.0.0/16` | Cilium Pod-CIDR (blockiert in Egress-Policies) |
| `network.serviceCIDR` | `10.32.0.0/12` | K8s Service-CIDR |
| `network.coreDNSClusterIP` | `10.32.0.10` | CoreDNS ClusterIP |

## Cilium

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `cilium.l7Visibility` | `true` | Hubble L7 HTTP-Monitoring (CiliumNetworkPolicy mit L7 rules) |

## RBAC

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `rbac.enabled` | `true` | Workload-RBAC (read-only) fuer Quarantine-Pods |
