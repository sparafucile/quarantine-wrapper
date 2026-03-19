"""Configuration from environment variables."""
import os

# Namespace detection
APP_NAME = os.getenv("APP_NAME", "openclaw")
APP_NAMESPACE = os.getenv("APP_NAMESPACE", f"{APP_NAME}-quarantine")
GW_NAMESPACE = os.getenv("GW_NAMESPACE", f"{APP_NAME}-quarantine-gw")
CLUSTER_DNS = os.getenv("CLUSTER_DNS", "p-k8s-cluster.local")

# K8s API (in-cluster)
K8S_API_URL = "https://kubernetes.default.svc"
K8S_TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
K8S_CA_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

# Gitea API
GITEA_URL = os.getenv("GITEA_URL", "https://gitea.sparafucile.net")
GITEA_TOKEN = os.getenv("GITEA_TOKEN", "")
GITEA_REPO = os.getenv("GITEA_REPO", "k8s-apps/quarantine-wrapper")
GITEA_BRANCH = os.getenv("GITEA_BRANCH", "main")
GITEA_VALUES_FILE = os.getenv("GITEA_VALUES_FILE", f"values-{APP_NAME}.yaml")

# ArgoCD API
ARGOCD_URL = os.getenv("ARGOCD_URL", "https://p-argocd-k8s.sparafucile.net")
ARGOCD_TOKEN = os.getenv("ARGOCD_TOKEN", "")
ARGOCD_APP_NAME = os.getenv("ARGOCD_APP_NAME", APP_NAME)

# mitmproxy
MITMPROXY_HOST = os.getenv("MITMPROXY_HOST", f"mitmproxy.{GW_NAMESPACE}.svc.{CLUSTER_DNS}")
MITMPROXY_API_PORT = int(os.getenv("MITMPROXY_API_PORT", "8081"))
MITMPROXY_PASSWORD = os.getenv("MITMPROXY_PASSWORD", "")

# Build info
VERSION = "1.0.0"
BUILD_NUMBER = os.getenv("BUILD_NUMBER", "dev")
BUILD_DATE = os.getenv("BUILD_DATE", "")

# CC state ConfigMap
CC_STATE_CM = "cc-state"

# Port
PORT = int(os.getenv("CC_PORT", "8080"))
