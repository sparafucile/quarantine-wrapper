"""ArgoCD API client for sync triggering and status."""
import logging
import httpx
import config

logger = logging.getLogger(__name__)


async def get_app_status() -> dict:
    """Get ArgoCD app sync/health status."""
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
        status = data.get("status", {})
        return {
            "sync": status.get("sync", {}).get("status", "Unknown"),
            "health": status.get("health", {}).get("status", "Unknown"),
            "revision": status.get("sync", {}).get("revision", "")[:12],
            "operationPhase": status.get("operationState", {}).get("phase", ""),
        }


async def trigger_sync() -> dict:
    """Trigger an ArgoCD sync for the wrapper app."""
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}/sync"
    async with httpx.AsyncClient(verify=False, timeout=15) as client:
        resp = await client.post(
            url,
            headers={
                "Cookie": f"argocd.token={config.ARGOCD_TOKEN}",
                "Content-Type": "application/json",
            },
            content="{}",
        )
        if resp.status_code == 200:
            return {"status": "ok", "message": "Sync triggered"}
        else:
            body = resp.text[:200]
            return {"status": "error", "message": body}
