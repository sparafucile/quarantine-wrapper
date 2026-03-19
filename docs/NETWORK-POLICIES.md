# NetworkPolicy-Konzept

Vollstaendige Dokumentation der Netzwerk-Isolation im quarantine-wrapper Chart.

## App-Namespace (`<appName>-quarantine`)

- **default-deny** (Ingress + Egress)
- **allow-intra-namespace** (Pod-zu-Pod)
- **allow-dns** (CoreDNS)
- **allow-egress-to-proxy** (bedingt: mitmproxy:8080 wenn enabled, sonst Squid:3128)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-lan-ingress** (LAN + kube-system + gateway-system, dynamische Ports)
- **allow-authentik-ingress** (wenn authentik.enabled: Authentik Outpost zu App-Pods)

## Gateway-Namespace (`<appName>-quarantine-gw`)

- **default-deny** (Ingress + Egress)
- **allow-ingress-from-quarantine** (App-Pods auf Squid-Port)
- **allow-ingress-from-quarantine-mitmproxy** (App-Pods + CC-Pod auf mitmproxy-Port 8080)
- **allow-mitmproxy-to-squid** (mitmproxy Egress zu Squid, upstream proxy chain)
- **allow-squid-from-mitmproxy** (Squid Ingress von mitmproxy)
- **allow-mitmweb-ui** (LAN + Gateway + Authentik auf Web-UI Port 8081)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-dns** (CoreDNS)
- **allow-ca-distributor-egress** (K8s API Defense-in-Depth)
- **allow-internet-egress** (Squid: Internet minus LAN/Pod/Service-CIDR)
- **allow-authentik-egress** (wenn authentik.enabled: Setup/Cleanup-Jobs zu Authentik)
- **allow-controlcenter-egress** (wenn controlcenter.enabled: K8s API, mitmproxy:8080+8081, Gitea:443, ArgoCD:443)
- **allow-controlcenter-ingress** (wenn controlcenter.enabled: LAN, Gateway, kube-system, Authentik)

## CiliumNetworkPolicies (KRITISCH)

K8s NetworkPolicies erkennen Cilium-Identitaeten nicht. Daher zusaetzlich:

### App-Namespace
- **allow-gateway-envoy-ingress** (fromEntities: host, ingress, kube-apiserver) — Pflicht fuer Gateway API

### GW-Namespace
- **quarantine-l7-visibility** (Hubble HTTP-Monitoring, nur wenn `cilium.l7Visibility: true`)
- **allow-ca-distributor-apiserver** (toEntities: kube-apiserver — nach DNAT)
- **allow-authentik-setup-egress** (toCIDR: Service-CIDR + toEndpoints — fuer PostSync-Job)
- **allow-authentik-setup-apiserver** (toEntities: kube-apiserver — Service-Discovery)
- **allow-authentik-cleanup-egress** (toCIDR + toEndpoints — fuer PreDelete-Job)
- **allow-authentik-cleanup-apiserver** (toEntities: kube-apiserver)
- **allow-controlcenter-egress** (toEntities: kube-apiserver + toEndpoints: mitmproxy:8081+8080 + toCIDR: Internet:443)

## Wichtige Regeln

### Egress UND Ingress pruefen

Bei `default-deny` in beiden Richtungen reicht eine Egress-Regel allein NICHT. Das Ziel muss auch eine passende Ingress-Regel haben, selbst fuer **intra-Namespace-Traffic**. Beispiel: CC → mitmproxy:8080 scheiterte obwohl der CC korrekten Egress hatte — die mitmproxy-Ingress-Policy erlaubte nur Traffic vom App-Namespace, nicht vom GW-Namespace.

### CiliumNP bei Cross-Namespace-Service-Zugriff

K8s NetworkPolicies mit `ipBlock: serviceCIDR` funktionieren bei Cilium NICHT fuer Egress, weil Cilium das DNAT VOR der Policy-Evaluation sieht. Immer `CiliumNetworkPolicy` mit `toEntities` oder `toEndpoints` verwenden.

### Gateway API braucht CiliumNP

Cilium Envoy (hostNetwork, `reserved:ingress` Identity) wird von K8s NetworkPolicies nicht erkannt. Jeder Namespace mit Gateway API HTTPRoutes braucht eine CiliumNetworkPolicy mit `fromEntities: [host, ingress, kube-apiserver]`.
