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
        try:
            with open(config.K8S_TOKEN_PATH) as f:
                _token_cache = f.read().strip()
        except Exception as e:
            logger.error(f"Failed to read K8s token from {config.K8S_TOKEN_PATH}: {e}")
            raise
    return _token_cache


def _get_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=config.K8S_CA_PATH)
    return ctx


async def k8s_get(path: str) -> dict:
    """GET request to K8s API."""
    import httpx
    url = f"{config.K8S_API_URL}{path}"
    try:
        async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {_get_token()}"})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"K8s API error (GET {path}): {e}")
        raise


async def k8s_patch(path: str, data: dict, content_type: str = "application/strategic-merge-patch+json") -> dict:
    """PATCH request to K8s API."""
    import httpx
    url = f"{config.K8S_API_URL}{path}"
    try:
        async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
            resp = await client.patch(
                url,
                headers={"Authorization": f"Bearer {_get_token()}", "Content-Type": content_type},
                content=json.dumps(data),
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"K8s API error (PATCH {path}): {e}")
        raise


async def k8s_delete(path: str) -> dict:
    """DELETE request to K8s API."""
    import httpx
    url = f"{config.K8S_API_URL}{path}"
    try:
        async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
            resp = await client.delete(url, headers={"Authorization": f"Bearer {_get_token()}"})
            return resp.json()
    except Exception as e:
        logger.error(f"K8s API error (DELETE {path}): {e}")
        raise


async def get_pods(namespace: str) -> list:
    """Get all pods in a namespace."""
    try:
        data = await k8s_get(f"/api/v1/namespaces/{namespace}/pods")
    except Exception as e:
        logger.error(f"K8s API error getting pods in {namespace}: {e}")
        raise
    
    pods = []
    for p in data.get("items", []):
        meta = p["metadata"]
        spec = p.get("spec", {})
        status = p["status"]

        # Build lookup: spec image (human-readable) by container name
        spec_images = {}
        for c in spec.get("containers", []) + spec.get("initContainers", []):
            spec_images[c["name"]] = c.get("image", "")

        containers = []
        for cs in status.get("containerStatuses", []) + status.get("initContainerStatuses", []):
            # Prefer spec image (has tag name) over status image (often resolved to digest)
            image = spec_images.get(cs["name"], cs.get("image", ""))
            containers.append({
                "name": cs["name"],
                "ready": cs.get("ready", False),
                "restarts": cs.get("restartCount", 0),
                "image": image,
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
    try:
        data = await k8s_get(f"/apis/networking.k8s.io/v1/namespaces/{namespace}/networkpolicies")
    except Exception as e:
        logger.error(f"K8s API error getting NetworkPolicies in {namespace}: {e}")
        raise
    
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
    try:
        data = await k8s_get(f"/apis/cilium.io/v2/namespaces/{namespace}/ciliumnetworkpolicies")
    except Exception as e:
        logger.error(f"K8s API error getting CiliumNetworkPolicies in {namespace}: {e}")
        raise
    
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
    try:
        async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=15) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {_get_token()}"})
            resp.raise_for_status()
            return resp.text
    except Exception as e:
        logger.error(f"K8s API error getting logs for {namespace}/{pod_name}: {e}")
        raise


async def get_configmap(namespace: str, name: str) -> dict | None:
    """Get a ConfigMap."""
    try:
        return await k8s_get(f"/api/v1/namespaces/{namespace}/configmaps/{name}")
    except Exception as e:
        logger.warning(f"ConfigMap not found {namespace}/{name}: {e}")
        return None


async def patch_configmap(namespace: str, name: str, data: dict) -> dict:
    """Patch a ConfigMap's data field."""
    try:
        return await k8s_patch(
            f"/api/v1/namespaces/{namespace}/configmaps/{name}",
            {"data": data},
        )
    except Exception as e:
        logger.error(f"K8s API error patching ConfigMap {namespace}/{name}: {e}")
        raise
