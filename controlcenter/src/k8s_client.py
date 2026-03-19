"""Kubernetes API client using in-cluster ServiceAccount."""
import ssl
import json
import logging
import config

logger = logging.getLogger(__name__)

_token_cache = None


def _get_token() -> str:
    global _token_cache
    if _token_cache is None:
        with open(config.K8S_TOKEN_PATH) as f:
            _token_cache = f.read().strip()
    return _token_cache


def _get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=config.K8S_CA_PATH)
    return ctx


async def k8s_get(path: str) -> dict:
    """GET request to K8s API."""
    import httpx
    url = f"{config.K8S_API_URL}{path}"
    async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {_get_token()}"})
        resp.raise_for_status()
        return resp.json()


async def k8s_patch(path: str, data: dict, content_type: str = "application/strategic-merge-patch+json") -> dict:
    """PATCH request to K8s API."""
    import httpx
    url = f"{config.K8S_API_URL}{path}"
    async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
        resp = await client.patch(
            url,
            headers={"Authorization": f"Bearer {_get_token()}", "Content-Type": content_type},
            content=json.dumps(data),
        )
        resp.raise_for_status()
        return resp.json()


async def k8s_delete(path: str) -> dict:
    """DELETE request to K8s API."""
    import httpx
    url = f"{config.K8S_API_URL}{path}"
    async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
        resp = await client.delete(url, headers={"Authorization": f"Bearer {_get_token()}"})
        return resp.json()


async def get_pods(namespace: str) -> list:
    """Get all pods in a namespace."""
    data = await k8s_get(f"/api/v1/namespaces/{namespace}/pods")
    pods = []
    for p in data.get("items", []):
        meta = p["metadata"]
        status = p["status"]
        containers = []
        for cs in status.get("containerStatuses", []) + status.get("initContainerStatuses", []):
            containers.append({
                "name": cs["name"],
                "ready": cs.get("ready", False),
                "restarts": cs.get("restartCount", 0),
                "image": cs.get("image", ""),
                "state": list(cs.get("state", {}).keys())[0] if cs.get("state") else "unknown",
            })
        pods.append({
            "name": meta["name"],
            "phase": status.get("phase", "Unknown"),
            "created": meta.get("creationTimestamp", ""),
            "containers": containers,
        })
    return pods


async def get_network_policies(namespace: str) -> list:
    """Get NetworkPolicies in a namespace."""
    data = await k8s_get(f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies")
    policies = []
    for p in data.get("items", []):
        spec = p.get("spec", {})
        policies.append({
            "name": p["metadata"]["name"],
            "type": "NetworkPolicy",
            "policyTypes": spec.get("policyTypes", []),
            "podSelector": spec.get("podSelector", {}),
        })
    return policies


async def get_cilium_policies(namespace: str) -> list:
    """Get CiliumNetworkPolicies in a namespace."""
    data = await k8s_get(f"/apis/cilium.io/v2/namespaces/{namespace}/ciliumnetworkpolicies")
    policies = []
    for p in data.get("items", []):
        policies.append({
            "name": p["metadata"]["name"],
            "type": "CiliumNetworkPolicy",
            "spec": p.get("spec", {}),
        })
    return policies


async def get_pod_logs(namespace: str, pod_name: str, tail_lines: int = 500) -> str:
    """Get pod logs."""
    import httpx
    url = f"{config.K8S_API_URL}/api/v1/namespaces/{namespace}/pods/{pod_name}/log?tailLines={tail_lines}"
    async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=15) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {_get_token()}"})
        resp.raise_for_status()
        return resp.text


async def get_configmap(namespace: str, name: str) -> dict | None:
    """Get a ConfigMap."""
    try:
        return await k8s_get(f"/api/v1/namespaces/{namespace}/configmaps/{name}")
    except Exception:
        return None


async def patch_configmap(namespace: str, name: str, data: dict) -> dict:
    """Patch a ConfigMap's data field."""
    return await k8s_patch(
        f"/api/v1/namespaces/{namespace}/configmaps/{name}",
        {"data": data},
    )
