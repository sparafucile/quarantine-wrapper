# Quarantine ControlCenter — Backlog

Stand: Session 199 (2026-03-19), CC v1.0.8 deployed.

## Aktueller Stand

CC v1.0.8 laeuft im `openclaw-quarantine-gw` Namespace.
URL: https://p-openclaw-quarantine-cc-k8s.sparafucile.net (hinter Authentik)
Image: `p-harbor-core-k8s.sparafucile.net/library/quarantine-controlcenter:1.0.8`

### Funktioniert
- Whitelist-Tab: Zeigt 11 Domains aus ArgoCD inline values
- Denied-Tab: Zeigt Squid TCP_DENIED Eintraege (aus Pod-Logs)
- Traffic-Tab: Sortierbar + filterbar (Status, Host), aber mitmproxy-Auth noch 403
- Pods-Tab: Zeigt Pods beider Namespaces mit korrekten Farben (Running=gruen, Succeeded=lila)
- Policies-Tab: NetworkPolicies + CiliumNetworkPolicies beider Namespaces
- ArgoCD-Status im Header (Synced/Revision)
- Version v1.0.8 im Footer

### Bugs (naechste Session fixen)
1. **Build-Info fehlt**: Footer zeigt nur `v1.0.8` ohne Build-Nummer. Ursache: `BUILD_NUMBER` und `BUILD_DATE` Env-Vars sind im Deployment-Template nicht gesetzt. Fix: Im `controlcenter.yaml` Template die Env-Vars aus der Jenkins-Pipeline durchreichen (oder aus dem Image-Digest ableiten).
2. **Health-Check Fehler**: Zeigt "mitmproxy API unreachable" weil mitmweb 403 zurueckgibt (Auth-Problem). Ausserdem wird der Health-Tab zyklisch refreshed (alle 15s) — soll nur manuell per Button refreshen.
3. **Headlamp-Links**: Format wurde auf `/c/main/{kind}/{ns}/{name}` geaendert — muss verifiziert werden ob das korrekt ist.
4. **Traffic-Tab leer**: mitmproxy REST API gibt 403 — Auth mit empty-username Basic Auth funktioniert nicht. Muss mitmweb Auth-Mechanismus verifizieren (evtl. Session-Cookie statt Basic Auth).
5. **Denied nach Freigabe leer**: Wenn "Freigeben" geklickt wird, wird die Domain zur ArgoCD-Whitelist hinzugefuegt. Danach ist der Denied-Tab leer weil der Squid-Pod restartet (neuer Pod = leere Logs). Fix: Squid-Logs persistent machen (PVC statt emptyDir) oder CC cached Denied-Eintraege in cc-state ConfigMap.
6. **Whitelist-Add Feedback**: Nach "Freigeben" ist unklar ob die Aenderung produktiv wirksam ist. Fix: ArgoCD-Sync triggern + Status "Committed -> Syncing -> Active" anzeigen.

## Backlog (priorisiert)

### P1 — Sofort-Fixes (v1.0.9)
- [ ] BUILD_NUMBER/BUILD_DATE im controlcenter.yaml Deployment-Template als Env-Vars
- [ ] Health-Tab: Kein Auto-Refresh, nur manueller Button
- [ ] Health-Tab: mitmproxy-Auth fixen (mitmweb Auth-Mechanismus verifizieren!)
- [ ] Traffic-Tab: Gleicher mitmproxy-Auth Fix
- [ ] Whitelist Add/Remove: ArgoCD-Sync nach Aenderung triggern
- [ ] Whitelist Add Feedback: Status-Anzeige "Committed -> Syncing -> Active"
- [ ] Denied-Tab nach Freigabe: Eintraege nicht leeren, sondern "freigegeben" markieren

### P2 — Persistente Denied-Logs
- [ ] Squid access.log persistent machen: PVC (100Mi Longhorn) fuer /var/log/squid statt emptyDir
- [ ] Oder: CC cached Denied-Eintraege in cc-state ConfigMap (einfacher, limitiert auf ~1000 Eintraege)

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
- [ ] Bypass-Modus: Zeitgesteuerte All-Domains-Freigabe implementieren (UI + Backend vorhanden, nicht getestet)
- [ ] CC Paketmanager-Templates: Schnell-Freigabe fuer npm, pip, apt Domains
- [ ] Favicons fuer CC + HelloWorld

## Architektur-Hinweise fuer die naechste Session

### Tokens/Secrets
- CC Gitea Token: ExternalSecret `cc-gitea-token` -> OpenBao `apps/claude/credentials` (key: `gitea-token`)
- CC ArgoCD Token: ExternalSecret `cc-argocd-token` -> OpenBao `apps/claude/credentials` (key: `argocd-token`)
- mitmweb Passwort: ExternalSecret `mitmweb-password` -> OpenBao `apps/openclaw-quarantine-gw/mitmweb-password`

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
