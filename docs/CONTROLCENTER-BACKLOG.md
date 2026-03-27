# Quarantine ControlCenter — Backlog

Stand: Session 200 (2026-03-19), CC v1.0.14 deployed.

## Aktueller Stand

CC v1.0.14 deployed im `<appName>-quarantine-gw` Namespace.
URL: `https://p-<appName>-quarantine-cc-k8s.sparafucile.net` (hinter Authentik)
Image: `p-harbor-core-k8s.sparafucile.net/library/quarantine-controlcenter:1.0.14`

### Funktioniert
- Whitelist-Tab: Domains aus ArgoCD inline values, Add/Remove mit Sync-Status-Feedback (Committed -> Syncing -> Active)
- Denied-Tab: Squid TCP_DENIED Eintraege, persistent gecached (cc-state ConfigMap), Freigabe markiert durchgestrichen
- Traffic-Tab: Sortierbar + filterbar, mitmproxy Auth via ?token=, mitmweb Deep-Links (/#/flows/{id}/request)
- Pods-Tab: Pods beider Namespaces mit Headlamp-Links, Klartext-Image-Namen (spec statt digest)
- Policies-Tab: NetworkPolicies + CiliumNetworkPolicies mit Headlamp-Links
- Health-Tab: Proxy-Chain-Check (mitmproxy -> Squid -> Internet), nur manuell per Button
- ArgoCD-Status im Header (Synced/Revision)
- Build-Info im Footer: Version | Build# | Commit-Hash | Datum
- CC Egress: Port 8080 (Proxy) + 8081 (Web-UI) in NetworkPolicy + CiliumNetworkPolicy

### Erledigt in Session 200

**P1 — Sofort-Fixes:**
- [x] BUILD_NUMBER/BUILD_DATE/BUILD_COMMIT via build.* Values (Jenkins Stage 2 schreibt sie)
- [x] Health-Tab: Token-Auth statt Basic Auth (?token= Query-Parameter)
- [x] Health-Tab: Auto-Refresh entfernt, nur manueller Button
- [x] Traffic-Tab: Auth funktionierte bereits (Token-Auth in mitmproxy_client.py)
- [x] Whitelist Add/Remove: ArgoCD-Sync + Status-Feedback (Committed -> Syncing -> Active)
- [x] Denied-Tab: Persistent Cache in cc-state ConfigMap + Client-Side Cache
- [x] CC Egress NetworkPolicy: Port 8080 fuer Proxy-Chain Health-Check

**P2 — Persistente Denied-Logs:**
- [x] CC cached Denied-Eintraege in cc-state ConfigMap (limitiert auf ~1000 Eintraege)

**P3 — CI/CD Verbesserungen:**
- [x] Jenkins Shared Library: `repoName` Parameter (Monorepo-Support)
- [x] Stage 2: build.number/date/commit Pattern (neben Legacy BUILD_NUMBER/BUILD_DATE)
- [x] Chart nach /chart migriert (konsistent mit allen k8s-apps Repos)
- [x] ArgoCD-App-Path: . -> chart

**Bonus:**
- [x] Headlamp-Links in Pods-Tab (Pods + Namespaces)
- [x] mitmweb Deep-Links in Traffic-Tab (/#/flows/{id}/request)
- [x] Pod-Image-Anzeige: spec.containers statt status.containerStatuses (Klartext statt Digest)
- [x] MITMWEB_URL Env-Var aus Helm-Template
- [x] CA-Trust initContainer fuer CC (SSL_CERT_FILE + REQUESTS_CA_BUNDLE)
- [x] Hello-World HTTPRoute: Duplizierte Route entfernt, Authentik-Schutz funktioniert
- [x] CiliumNetworkPolicy Headlamp-Links: Korrektes ciliumnetworkpolicies.cilium.io Format
- [x] clusterDNS: Alle hardcoded DNS durch .Values.clusterDNS ersetzt
- [x] mitmproxy Ingress-Policy: CC als erlaubte Quelle fuer Port 8080 (Root Cause Health-Check)
- [x] Health-Check zeigt Test-URL im UI an

**P4 (erledigt):**
- [x] authentik-setup: Scannt jetzt App- UND GW-Namespace nach Services mit Authentik-Label
- [x] Cleanup-Script: Enthaelt GW-Namespace-Prefix fuer vollstaendiges Aufraumen

**P5 (erledigt):**
- [x] App-spezifische values-Datei: War bereits nach ArgoCD inline values migriert

**P6 (erledigt):**
- [x] Paketmanager-Templates: npm, pip/PyPI, apt/Debian, Docker Hub, GitHub API
- [x] Favicons fuer CC (blauer Q-Badge) und HelloWorld (HW-Badge)
- [x] Batch-Whitelist: "Alle Freigeben" Button im Denied-Tab

## Offenes Backlog

### Verbleibend
- [ ] Bypass-Modus: Zeitgesteuerte All-Domains-Freigabe testen (UI + Backend vorhanden)
- [ ] Squid access.log persistent machen: PVC fuer /var/log/squid (optional, cc-state reicht)
- [ ] Traffic-Tab: Auto-Refresh Intervall konfigurierbar machen
- [ ] ArgoCD Sync-Hook-Probleme (Hooks blockieren bei jedem Sync bei manchen Apps)
- [ ] Jenkins CI/CD Race Condition (GIT_PREVIOUS_SUCCESSFUL_COMMIT)

## Architektur-Hinweise

### Tokens/Secrets
- CC Gitea Token: ExternalSecret `cc-gitea-token` -> OpenBao `apps/claude/credentials` (key: `gitea-token`)
- CC ArgoCD Token: ExternalSecret `cc-argocd-token` -> OpenBao `apps/claude/credentials` (key: `argocd-token`)
- mitmweb Passwort: ExternalSecret `mitmweb-password` -> OpenBao `apps/<appName>-quarantine-gw/mitmweb-password`

### mitmweb Auth-Mechanismus
mitmweb (alle aktuellen Versionen) verwendet `?token=PASSWORD` als Query-Parameter fuer API-Auth. Basic Auth (leerer Username) funktioniert NICHT. Das gilt fuer alle REST API Endpunkte (/flows, /events, etc.). Quelle: mitmproxy Source + CVE-2025-23217 Auth-Enforcement.

### CiliumNetworkPolicies
CC hat eine eigene CNP `allow-controlcenter-egress` mit:
- toEntities: kube-apiserver
- toCIDR: serviceCIDR (10.32.0.0/12) Port 443
- toEndpoints: mitmproxy:8081 (Web-UI) + mitmproxy:8080 (Proxy, fuer Health-Check)
- toCIDR: 0.0.0.0/0 Port 443 (Gitea, ArgoCD)
- DNS zu kube-dns

Zusaetzlich braucht mitmproxy eine **Ingress**-Policy die den CC-Pod auf Port 8080 akzeptiert (`allow-ingress-from-quarantine-mitmproxy` mit `podSelector: app: controlcenter`).

### CI/CD
- Jenkinsfile: `appname: 'quarantine-controlcenter'`, `repoName: 'quarantine-wrapper'`, `dockerpath: 'controlcenter'`
- Stage 2 schreibt `build.number`, `build.date`, `build.commit` in `chart/values.yaml`
- Deployment-Template liest `build.*` Values und setzt BUILD_NUMBER/BUILD_DATE/BUILD_COMMIT Env-Vars

### Bekannte Cilium-Probleme
- K8s NetworkPolicies mit ipBlock:serviceCIDR funktionieren bei Cilium NICHT fuer Egress (DNAT-Problem)
- IMMER CiliumNetworkPolicy mit toEntities/toEndpoints zusaetzlich erstellen
- PreDelete-Hooks brauchen eigene CNPs (laufen wenn alle Policies aktiv sind)
