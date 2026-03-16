# NetworkPolicy-Konzept

Vollstaendige Dokumentation der Netzwerk-Isolation im quarantine-wrapper Chart.

## App-Namespace (`<appName>-quarantine`)

- **default-deny** (Ingress + Egress)
- **allow-intra-namespace** (Pod-zu-Pod)
- **allow-dns** (CoreDNS)
- **allow-egress-to-proxy** (bedingt: mitmproxy:8080 wenn enabled, sonst Squid:3128)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-lan-ingress** (LAN + kube-system + gateway-system, dynamische Ports)

## Gateway-Namespace (`<appName>-quarantine-gw`)

- **default-deny** (Ingress + Egress)
- **allow-ingress-from-quarantine** (App-Pods auf Squid-Port)
- **allow-ingress-from-quarantine-mitmproxy** (App-Pods auf mitmproxy-Port, wenn enabled)
- **allow-mitmproxy-to-squid** (mitmproxy Egress zu Squid, upstream proxy chain)
- **allow-squid-from-mitmproxy** (Squid Ingress von mitmproxy)
- **allow-mitmweb-ui** (LAN + Gateway auf Web-UI)
- **allow-argocd-ingress** (ArgoCD Management)
- **allow-dns** (CoreDNS)
- **allow-ca-distributor-egress** (K8s API Defense-in-Depth)
- **allow-internet-egress** (Squid: Internet minus LAN/Pod/Service-CIDR)
- **allow-authentik-egress** (wenn authentik.enabled: PostSync-Job zu Authentik)

## CiliumNetworkPolicies (KRITISCH)

K8s NetworkPolicies erkennen Cilium-Identitaeten nicht. Daher zusaetzlich:

- **allow-gateway-envoy-ingress** (fromEntities: host, ingress, kube-apiserver) — Pflicht fuer Gateway API
- **quarantine-l7-visibility** (Hubble HTTP-Monitoring, nur wenn `cilium.l7Visibility: true`)
- **allow-ca-distributor-apiserver** (toEntities: kube-apiserver — nach DNAT)
- **allow-authentik-setup-egress** (toCIDR: Service-CIDR + toEndpoints — fuer PostSync-Job)
