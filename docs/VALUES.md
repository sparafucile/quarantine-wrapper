# Values-Referenz

Vollstaendige Parameter-Dokumentation fuer den quarantine-wrapper Helm Chart (`chart/`).

## Pflicht

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `appName` | `"example"` | App-Identifier, steuert alle dynamischen Namen. MUSS in ArgoCD ueberschrieben werden! |
| `clusterDNS` | `"p-k8s-cluster.local"` | Cluster-DNS-Domain (kubeadm --service-dns-domain) |

## Services (Ingress)

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

## Authentik

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `authentik.enabled` | `true` | Authentik SSO global |
| `authentik.namespace` | `authentik` | Authentik Namespace |
| `authentik.outpostPk` | `1` | Fallback Outpost PK (Auto-Discovery aktiv) |
| `authentik.openbaoPath` | auto | Default: `infra/authentik/api-token` (shared) |

Wenn `authentik.enabled`: PostSync-Job erstellt automatisch Proxy-Provider, Applications und updated den Embedded Outpost. Service-Discovery scannt **beide** Namespaces (App + GW) nach Services mit Label `quarantine.sparafucile.net/authentik: "true"`. Flows (authorization + invalidation) werden auto-discovered via `/api/v3/flows/instances/`.

## Egress / Squid-Whitelist

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `egress.squidAllowedDomains` | `[placeholder...]` | Domain-Whitelist fuer Squid (Default: Dummy-Domain, blockiert alles) |
| `egress.extraEgressRules` | `[]` | Zusaetzliche K8s NetworkPolicy egress rules |

**WICHTIG:** Der Default-Wert enthaelt eine Dummy-Domain (`placeholder.quarantine.internal`), sodass Squid standardmaessig ALLES blockiert. Jede Instanz MUSS eigene Domains in ihrer Values-Datei eintragen. Eine leere Liste (`[]`) wuerde alles erlauben — das ist NICHT der Default. Subdomains werden automatisch eingeschlossen (`.example.com` matcht auch `sub.example.com`).

```yaml
egress:
  squidAllowedDomains:
    - generativelanguage.googleapis.com   # Google Gemini API
    - api.openai.com                      # OpenAI API
    - registry.npmjs.org                  # npm Registry
```

Der Squid-Pod restartet automatisch bei Aenderungen an der Whitelist (Checksum-Annotation).

## Proxy-Kette

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `squid.port` | `3128` | Squid Proxy Port |
| `mitmproxy.enabled` | `true` | mitmproxy TLS-Interception + upstream-Modus |
| `mitmproxy.proxyPort` | `8080` | mitmproxy Proxy Port |
| `mitmproxy.webPort` | `8081` | mitmweb UI Port |
| `mitmproxy.hostname` | auto | Default: `p-<appName>-mitmweb-k8s.<clusterDomain>` |
| `mitmproxy.openbaoPath` | auto | Default: `apps/quarantine/<appName>/mitmweb-password` |
| `mitmproxy.storageClass` | `longhorn` | PVC StorageClass |

Die Proxy-Env-Vars (`http_proxy`, `https_proxy`, etc.) werden automatisch angepasst:

- **`mitmproxy.enabled: true`** — Apps nutzen `mitmproxy:8080` als Proxy. mitmproxy laeuft im `--mode upstream:http://squid:3128/` und leitet an Squid weiter. Alle Requests sind in mitmweb sichtbar (auch von Squid abgelehnte). Nur Squid hat Internet-Egress.
- **`mitmproxy.enabled: false`** — Apps nutzen `squid:3128` direkt. Keine TLS-Interception, kein mitmweb. Squid-Whitelist greift trotzdem.

### Automatisch gesetzte Proxy-Env-Vars

Der `proxyEnv` Helm-Helper setzt folgende Umgebungsvariablen fuer alle Quarantine-Pods:

| Variable | Wert | Beschreibung |
|----------|------|-------------|
| `HTTP_PROXY` / `http_proxy` | `http://mitmproxy.<gw-ns>:8080` (oder `squid:3128`) | HTTP-Proxy |
| `HTTPS_PROXY` / `https_proxy` | (gleich) | HTTPS-Proxy |
| `NO_PROXY` / `no_proxy` | `127.0.0.1,localhost,.<app-ns>.svc,.<gw-ns>.svc,<serviceCIDR>` | Proxy-Bypass |
| `NODE_USE_ENV_PROXY` | `1` | **Pflicht fuer Node.js 24+** — undici/fetch ignoriert Proxy-Vars ohne dieses Flag |
| `SSL_CERT_FILE` | `/etc/ssl/custom/ca-certificates.crt` | TLS CA-Trust (mitmproxy) |
| `REQUESTS_CA_BUNDLE` | `/etc/ssl/custom/ca-certificates.crt` | Python requests CA-Trust |
| `NODE_EXTRA_CA_CERTS` | `/etc/ssl/custom/ca-certificates.crt` | Node.js CA-Trust |

## CA-Zertifikat

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `ca.enabled` | `true` | CA-Distribution aktivieren |
| `ca.openbaoPath` | auto | Default: `apps/quarantine/<appName>/mitmproxy-ca` |
| `ca.secretName` | `mitmproxy-ca` | K8s Secret Name |

## ControlCenter (Web-UI)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `controlcenter.enabled` | `false` | ControlCenter aktivieren |
| `controlcenter.image.repository` | Harbor Registry | CC Container Image |
| `controlcenter.image.tag` | `"1.0.14"` | CC Image Tag (von Jenkins gesetzt) |
| `controlcenter.port` | `8080` | CC HTTP Port |
| `controlcenter.hostname` | auto | Default: `p-<appName>-quarantine-cc-k8s.<domain>` |

Das CC bekommt automatisch: mitmproxy-CA (initContainer), `PROXY_URL` (expliziter Proxy-Zugang fuer Health-Check), `MITMWEB_URL` (fuer Deep-Links), `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` (CA-Trust), sowie `BUILD_NUMBER`/`BUILD_DATE`/`BUILD_COMMIT` aus der `build:` Section.

## Build (Jenkins CI/CD)

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `build.number` | `"dev"` | Jenkins Build-Nummer (von Stage 2 gesetzt) |
| `build.date` | `""` | Build-Datum (von Stage 2 gesetzt) |
| `build.commit` | `""` | Git Short-Hash (von Stage 2 gesetzt) |

## Hello-World Debug-Pod

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `helloWorld.enabled` | `false` | Debug-Pod aktivieren |
| `helloWorld.port` | `8080` | HTTP Port |
| `helloWorld.hostname` | auto | Default: `p-<appName>-hello-k8s.<domain>` (via Helper) |

## Netzwerk

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `network.lanCIDR` | `192.168.4.0/24` | LAN-Subnetz |
| `network.podCIDR` | `10.244.0.0/16` | Cilium Pod-CIDR |
| `network.serviceCIDR` | `10.32.0.0/12` | K8s Service-CIDR |
| `network.coreDNSClusterIP` | `10.32.0.10` | CoreDNS ClusterIP |

## Cilium

| Parameter | Default | Beschreibung |
|-----------|---------|-------------|
| `cilium.l7Visibility` | `false` | Hubble L7 HTTP-Monitoring |
