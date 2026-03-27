# Lessons Learned

Gesammelte Erkenntnisse und Pitfalls aus der Entwicklung des quarantine-wrapper Charts. Chronologisch nach Version sortiert.

---

## Session 198 (v1.4.x)

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

### OutOfSync bei ExternalSecrets und HTTPRoutes

ServerSideApply erzeugt Diffs bei ExternalSecrets (ESO-Webhook ergaenzt Defaults) und HTTPRoutes (API-Server ergaenzt group/kind/weight). Fix: Explizite Defaults in Templates setzen (ESO: `conversionStrategy: Default`, `decodingStrategy: None`, `metadataPolicy: None`, `creationPolicy: Owner`, `deletionPolicy: Retain`, `engineVersion: v2`, `mergePolicy: Replace`; HTTPRoute: `group: ""`, `kind: Service`, `weight: 1`). `ignoreDifferences` als Fallback konfiguriert.

### subPath ConfigMap-Mounts sind immutable

Apps die ihre Config via rename-Pattern aktualisieren (write temp → rename) koennen subPath-Mounts nicht verwenden — rename fuehrt zu EBUSY. Loesung: initContainer kopiert Config von ConfigMap-Volume auf PVC, App-Container mountet nur das PVC-Verzeichnis.

### python:3.12-slim statt alpine fuer Jobs

In Quarantine-Umgebungen kann `apk add` nicht funktionieren (Alpine-Repos nicht in Squid-ACL). `python:3.12-slim` (Debian bookworm) hat openssl vorinstalliert. Grundregel: Kein Paketmanager-Zugriff in Quarantine ohne explizites Whitelisting.

### mitmweb Passwort-Management

mitmweb generiert bei jedem Start ein zufaelliges Token. Fuer vorhersagbaren Zugang: Passwort in OpenBao generieren und via `--set web_password=$(MITMWEB_PASSWORD)` uebergeben (K8s env var substitution in args).

---

## v1.5.0

### CA Trust via cat statt update-ca-certificates

alpine:3.21 (Basis-Image) hat `update-ca-certificates` NICHT vorinstalliert — es liegt im Paket `ca-certificates`, das erst via `apk add` installiert werden muesste. In Quarantine-Umgebungen ist `apk add` nicht moeglich (Alpine-Repos nicht gewhitelistet). Fix: `cat /etc/ssl/certs/ca-certificates.crt /ca-cert/mitmproxy-ca-cert.pem > /shared-certs/ca-certificates.crt`. Funktioniert mit JEDEM Image das `/etc/ssl/certs/ca-certificates.crt` hat (alpine, debian, ubuntu, python, node).

### mitmproxy erwartet kombiniertes CA-File

mitmproxy erwartet Key und Cert **kombiniert** in einer einzigen Datei `mitmproxy-ca.pem` im confdir (`/home/mitmproxy/.mitmproxy/`). Werden separate Dateien angelegt (`mitmproxy-ca-cert.pem` + `mitmproxy-ca.pem` nur mit Key), generiert mitmproxy beim Start eine NEUE CA — alle bestehenden CA-Bundles in Quarantine-Pods matchen dann nicht mehr. Fix: `cat key.pem cert.pem > mitmproxy-ca.pem` im initContainer.

### Egress-NetworkPolicy muss zum aktiven Proxy zeigen

Die `allow-egress-to-proxy` NetworkPolicy im Quarantine-Namespace muss den **ersten Hop** der Proxy-Kette targeten. Bei `mitmproxy.enabled: true` ist das `app: mitmproxy-debug` auf Port 8080, bei `false` ist es `app: egress-proxy` auf Port 3128. Zusaetzlich braucht der GW-Namespace eine eigene Ingress-Policy `allow-ingress-from-quarantine-mitmproxy` fuer mitmproxy.

### Default-sichere Squid-Whitelist

`egress.squidAllowedDomains` darf NIEMALS leer sein (`[]`), da eine leere ACL in Squid ALLES erlaubt. Default-Wert ist `placeholder.quarantine.internal` — eine nicht-existente Dummy-Domain, die effektiv allen Traffic blockiert. Echte Domains muessen explizit eingetragen werden.

---

## v1.6.0

### NODE_USE_ENV_PROXY fuer Node.js 24+

**Problem:** Node.js 24+ mit undici/fetch ignoriert HTTP_PROXY/HTTPS_PROXY Environment-Variablen standardmaessig. In der Quarantine-Umgebung fuehrt das dazu, dass HTTPS-Requests direkt rausgehen und von der NetworkPolicy blockiert werden → Timeout.

**Fix:** `NODE_USE_ENV_PROXY=1` als Environment-Variable setzen. Ist im `proxyEnv` Helm-Helper enthalten und wird automatisch an alle Pods verteilt.

---

## v1.6.1

### Recreate-Strategie bei RWO-PVCs

**Problem:** ReadWriteOnce-PVCs koennen nur auf einem Node gemountet werden. Mit RollingUpdate-Strategie startet K8s den neuen Pod BEVOR der alte terminiert wird. Landet der neue Pod auf einem anderen Node, haengt er ewig in `Init:0/x` weil die PVC nicht gemountet werden kann.

**Fix:** `strategy.type: Recreate` im Deployment-Spec. K8s terminiert erst den alten Pod, dann startet es den neuen — PVC ist immer frei.

### ServerSideApply Array-Merge bei initContainern

**Problem:** SSA mergt Arrays nach `name`-Feld statt sie zu ersetzen. Beim Umbenennen eines initContainers (z.B. `copy-config` → `merge-config`) bleibt der alte bestehen, das Deployment hat dann mehr initContainers als erwartet.

**Fix:** Einmalig mit `Replace=true` ueber ArgoCD syncen: `POST /api/v1/applications/<app>/sync` mit `syncOptions: {items: ["Replace=true"]}` und gezieltem `resources`-Filter fuer das betroffene Deployment.

### Cilium Stale Endpoint nach Node-Wechsel

**Problem:** Wenn ein Pod durch Recreate-Strategie auf einen anderen Node wandert, kann Cilium's Envoy den alten Endpoint gecacht halten. Ergebnis: "upstream connect error / Connection timed out" (503) obwohl der Pod Ready ist und kubelet Health-Checks bestehen.

**Fix:** Pod loeschen (erneuter Restart), damit Cilium den Endpoint frisch programmiert. Tritt besonders nach erstmaliger Umstellung auf Recreate-Strategie auf.

---

## Session 200 (ControlCenter v1.0.14)

### mitmweb Auth: Token statt Basic Auth

**Problem:** CC Health-Check und Traffic-Tab zeigten 403 bei mitmweb API-Calls. `httpx.BasicAuth(username="", password=...)` wurde abgelehnt.

**Fix:** `?token=PASSWORD` als Query-Parameter (mitmweb-Standard seit CVE-2025-23217). Basic Auth funktioniert NICHT fuer die REST API.

### Duplizierte HTTPRoute ueberschreibt Authentik-Schutz

**Problem:** `hello-world.yaml` enthielt eine HTTPRoute die IMMER auf `hello-world:8080` zeigte (keine Authentik-Bedingung). `httproutes.yaml` enthielt dieselbe Route MIT Authentik-Bedingung. Helm rendert Templates alphabetisch und gibt beide als separate YAML-Dokumente aus. Bei identischem `metadata.name` ueberschreibt SSA das Feld mit dem zuletzt angewendeten Wert — die `hello-world.yaml`-Version (`h` < `ht`) wurde zuerst gerendert, aber SSAs Field-Ownership-Tracking verhinderte das Update durch `httproutes.yaml`.

**Fix:** HTTPRoute nur noch in `httproutes.yaml` definieren. Bei SSA-Konflikten: Route loeschen, dann neu syncen (SSA-Field-Ownership). KEINE doppelten Ressourcen mit gleichem `metadata.name` in verschiedenen Templates!

### Ingress-Policy auf Empfaenger-Seite pruefen

**Problem:** CC konnte mitmproxy:8080 nicht erreichen (ConnectTimeout). CC-Egress war korrekt (CiliumNP + K8s-NP). Root Cause: Die **Ingress**-Policy auf mitmproxy erlaubte Port 8080 NUR vom App-Namespace, nicht vom GW-Namespace (wo der CC lebt). `default-deny-ingress` blockierte den intra-NS-Traffic.

**Fix:** `allow-ingress-from-quarantine-mitmproxy` um CC-Pod als Ingress-Quelle erweitert. **Immer BEIDE Seiten pruefen: Egress (Sender) UND Ingress (Empfaenger).**

### CC braucht eigene CA-Trust (kein Kyverno im GW-NS)

**Problem:** CC im GW-Namespace hat keine Proxy-EnvVars und kein CA-Trust — Kyverno injiziert nur im App-Namespace.

**Fix:** CC Deployment bekommt `trust-mitmproxy-ca` initContainer + `SSL_CERT_FILE`/`REQUESTS_CA_BUNDLE` Env-Vars + `PROXY_URL` fuer expliziten Proxy-Zugang im Health-Check.

### Headlamp CRD-URLs verwenden Plural-Namen

**Falsch:** `/c/main/customresources/cilium.io/v2/CiliumNetworkPolicy/{ns}/{name}` (404)
**Richtig:** `/c/main/customresources/ciliumnetworkpolicies.cilium.io/{ns}/{name}`

Headlamp verwendet `{crd-plural}.{api-group}` als URL-Segment fuer Custom Resources.

### Chart-Pfad: immer `/chart` verwenden

Alle k8s-apps Repos nutzen `chart/` als Helm-Chart-Verzeichnis. ArgoCD Source-Path MUSS `chart` sein (nicht `.`). Macht Jenkins Stage 0 (Helm Validate) und Stage 2 (Tag-Update) kompatibel mit den Defaults der Shared Library.

### hardcoded DNS durch Values ersetzen

`p-k8s-cluster.local` war in 6+ Templates hardcoded. Neuer Value `clusterDNS` (Default: `p-k8s-cluster.local`) in `_helpers.tpl`, `controlcenter.yaml`, `authentik-setup.yaml`, `authentik-cleanup.yaml`.
