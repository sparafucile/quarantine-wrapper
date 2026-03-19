# Quarantine ControlCenter — Backlog

Stand: Session 200 (2026-03-19), CC v1.0.9 in Arbeit.

## Aktueller Stand

CC v1.0.9 deployed im `openclaw-quarantine-gw` Namespace.
URL: https://p-openclaw-quarantine-cc-k8s.sparafucile.net (hinter Authentik)
Image: `p-harbor-core-k8s.sparafucile.net/library/quarantine-controlcenter:1.0.9`

### Funktioniert
- Whitelist-Tab: Zeigt Domains aus ArgoCD inline values, Add/Remove mit Sync-Status-Feedback
- Denied-Tab: Zeigt Squid TCP_DENIED Eintraege, persistent gecached (cc-state ConfigMap)
- Traffic-Tab: Sortierbar + filterbar (Status, Host), mitmproxy Auth via ?token= funktioniert
- Pods-Tab: Zeigt Pods beider Namespaces mit korrekten Farben (Running=gruen, Succeeded=lila)
- Policies-Tab: NetworkPolicies + CiliumNetworkPolicies beider Namespaces
- ArgoCD-Status im Header (Synced/Revision)
- Build-Info im Footer: Version | Build# | Commit-Hash | Datum
- Health-Tab: Proxy-Chain-Check nur manuell per Button (kein Auto-Refresh)

### Gefixt in v1.0.9 (P1)
1. **Build-Info**: Deployment-Template nutzt jetzt `build.number`/`build.date`/`build.commit` statt der leeren `controlcenter.buildNumber`/`buildDate`. Footer zeigt: `v1.0.9 | Build #X | abc12345 | 2026-03-19`.
2. **Health-Tab Auth**: `health_check.py` nutzt jetzt `?token=PASSWORD` statt Basic Auth — identisch zur funktionierenden `mitmproxy_client.py`. Root Cause: mitmweb akzeptiert Token-Auth via Query-Parameter, NICHT Basic Auth.
3. **Health-Tab Auto-Refresh entfernt**: Nur Whitelist/Denied/Traffic/Pods werden automatisch refreshed. Health nur manuell per Button.
4. **Traffic-Tab**: War bereits funktional (Logs zeigten 200 OK mit Token-Auth). Kein Code-Fix noetig.
5. **Whitelist Add/Remove Feedback**: Sync-Status-Indikator "Committed → Syncing → Active" in der UI. Pollt ArgoCD-Status bis Synced.
6. **Denied-Tab Persistenz**: Client-seitiger Cache UND Server-seitiger Cache in `cc-state` ConfigMap. Eintraege ueberleben Squid-Restarts. Freigegebene Domains werden durchgestrichen markiert statt geloescht.

## Backlog (priorisiert)

### P2 — Persistente Denied-Logs (ERLEDIGT via cc-state)
- [x] CC cached Denied-Eintraege in cc-state ConfigMap (limitiert auf ~1000 Eintraege)
- [ ] Optional: Squid access.log persistent machen: PVC fuer /var/log/squid (noch nicht noetig)

### P3 — CI/CD Verbesserungen
- [ ] Jenkins Shared Library: `repoName` Parameter hinzufuegen (aktuell: appname = Image-Name = Repo-Name, funktioniert nicht fuer Monorepos)
- [ ] Jenkinsfile im Wrapper: Stage 2 (Tag-Update) ueberspringen oder auf korrektes Repo zeigen
- [ ] Automatisches Image-Tag-Update in values.yaml nach Jenkins-Build

### P4 — Authentik-Integration
- [ ] authentik-setup Script: GW-Namespace nach Services mit `quarantine.sparafucile.net/authentik` Label scannen (aktuell wird CC-Provider manuell erstellt)
- [ ] Cleanup-Job: DNS-Egress fuer Setup/Cleanup-Pods pruefen

### P5 — Architektur-Cleanup
- [ ] values-openclaw.yaml: Domains aus Datei in ArgoCD inline values migrieren, Datei aus Repo loeschen
- [ ] ArgoCD openclaw App: Sync-Hook-Probleme loesen (Hooks blockieren bei jedem Sync)

### P6 — Weitere Features
- [ ] Bypass-Modus: Zeitgesteuerte All-Domains-Freigabe testen (UI + Backend vorhanden)
- [ ] CC Paketmanager-Templates: Schnell-Freigabe fuer npm, pip, apt Domains
- [ ] Favicons fuer CC + HelloWorld
- [ ] Headlamp-Links: Format `/c/main/{kind}/{ns}/{name}` verifizieren

## Architektur-Hinweise fuer die naechste Session

### Tokens/Secrets
- CC Gitea Token: ExternalSecret `cc-gitea-token` -> OpenBao `apps/claude/credentials` (key: `gitea-token`)
- CC ArgoCD Token: ExternalSecret `cc-argocd-token` -> OpenBao `apps/claude/credentials` (key: `argocd-token`)
- mitmweb Passwort: ExternalSecret `mitmweb-password` -> OpenBao `apps/openclaw-quarantine-gw/mitmweb-password`

### mitmweb Auth-Mechanismus (Lesson Learned v1.0.9)
mitmweb (alle aktuellen Versionen) verwendet `?token=PASSWORD` als Query-Parameter fuer API-Auth. Basic Auth (leerer Username) funktioniert NICHT. Das gilt fuer alle REST API Endpunkte (/flows, /events, etc.). Quelle: mitmproxy Source + CVE-2025-23217 Auth-Enforcement.

### CiliumNetworkPolicies
CC hat eine eigene CNP `allow-controlcenter-egress` mit:
- toEntities: kube-apiserver
- toCIDR: serviceCIDR (10.32.0.0/12) Port 443
- toEndpoints: mitmproxy:8081 (API)
- toCIDR: 0.0.0.0/0 Port 443 (Gitea, ArgoCD)
- DNS zu kube-dns

### Bekannte Cilium-Probleme
- K8s NetworkPolicies mit ipBlock:serviceCIDR funktionieren bei Cilium NICHT fuer Egress (DNAT-Problem)
- IMMER CiliumNetworkPolicy mit toEntities/toEndpoints zusaetzlich erstellen
- PreDelete-Hooks brauchen eigene CNPs (laufen wenn alle Policies aktiv sind)
