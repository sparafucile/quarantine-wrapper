"""Quarantine ControlCenter — FastAPI Backend."""
import logging
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

import config
import k8s_client
import gitea_client
import argocd_client
import squid_parser
import mitmproxy_client
import health_check
import bypass_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("controlcenter")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info(f"Quarantine ControlCenter v{config.VERSION} starting")
    logger.info(f"App: {config.APP_NAME}, NS: {config.APP_NAMESPACE}/{config.GW_NAMESPACE}")
    await bypass_scheduler.init()
    yield
    logger.info("Shutting down")


app = FastAPI(title="Quarantine ControlCenter", version=config.VERSION, lifespan=lifespan)

# Static files
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


# --- Models ---
class DomainAction(BaseModel):
    domain: str


class BypassAction(BaseModel):
    duration_minutes: int


# --- API Routes ---

@app.get("/api/info")
async def get_info():
    """Build and version info."""
    return {
        "version": config.VERSION,
        "build_number": config.BUILD_NUMBER,
        "build_date": config.BUILD_DATE,
        "app_name": config.APP_NAME,
        "app_namespace": config.APP_NAMESPACE,
        "gw_namespace": config.GW_NAMESPACE,
    }


@app.get("/api/config")
async def get_config():
    """Current Squid whitelist and configuration."""
    try:
        content, _ = await gitea_client.get_values_file()
        domains = gitea_client.parse_whitelist(content)
        bypass = bypass_scheduler.get_state()
        return {
            "whitelist": domains,
            "bypass": bypass,
            "values_file": config.GITEA_VALUES_FILE,
        }
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/whitelist/add")
async def add_to_whitelist(action: DomainAction):
    """Add domain to Squid whitelist via GitOps."""
    domain = action.domain.strip().lower()
    if not domain:
        raise HTTPException(400, "Domain required")

    try:
        content, sha = await gitea_client.get_values_file()
        domains = gitea_client.parse_whitelist(content)
        if domain in domains:
            return {"status": "exists", "domain": domain}

        domains.append(domain)
        new_content = gitea_client.update_whitelist(content, domains)
        await gitea_client.update_values_file(
            new_content, sha, f"controlcenter: add {domain} to squid whitelist"
        )

        # Trigger ArgoCD sync
        sync_result = await argocd_client.trigger_sync()
        return {"status": "added", "domain": domain, "sync": sync_result}
    except Exception as e:
        logger.error(f"Failed to add domain: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/whitelist/remove")
async def remove_from_whitelist(action: DomainAction):
    """Remove domain from Squid whitelist via GitOps."""
    domain = action.domain.strip().lower()
    try:
        content, sha = await gitea_client.get_values_file()
        domains = gitea_client.parse_whitelist(content)
        if domain not in domains:
            return {"status": "not_found", "domain": domain}

        domains.remove(domain)
        new_content = gitea_client.update_whitelist(content, domains)
        await gitea_client.update_values_file(
            new_content, sha, f"controlcenter: remove {domain} from squid whitelist"
        )
        sync_result = await argocd_client.trigger_sync()
        return {"status": "removed", "domain": domain, "sync": sync_result}
    except Exception as e:
        logger.error(f"Failed to remove domain: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/squid/denied")
async def get_denied_domains():
    """Get domains denied by Squid from pod logs."""
    try:
        denied = await squid_parser.get_denied_domains()
        return {"denied": denied, "count": len(denied)}
    except Exception as e:
        logger.error(f"Failed to get denied domains: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/traffic")
async def get_traffic():
    """Get recent mitmproxy traffic flows."""
    try:
        flows = await mitmproxy_client.get_flows()
        return {"flows": flows, "count": len(flows)}
    except Exception as e:
        logger.error(f"Failed to get traffic: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/pods")
async def get_pods():
    """Get pod status for both namespaces."""
    try:
        app_pods = await k8s_client.get_pods(config.APP_NAMESPACE)
        gw_pods = await k8s_client.get_pods(config.GW_NAMESPACE)
        return {"app_namespace": config.APP_NAMESPACE, "app_pods": app_pods,
                "gw_namespace": config.GW_NAMESPACE, "gw_pods": gw_pods}
    except Exception as e:
        logger.error(f"Failed to get pods: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/policies")
async def get_policies():
    """Get NetworkPolicies and CiliumNetworkPolicies for both namespaces."""
    try:
        result = {}
        for ns in [config.APP_NAMESPACE, config.GW_NAMESPACE]:
            np = await k8s_client.get_network_policies(ns)
            cnp = await k8s_client.get_cilium_policies(ns)
            result[ns] = {"networkPolicies": np, "ciliumPolicies": cnp}
        return result
    except Exception as e:
        logger.error(f"Failed to get policies: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/health")
async def get_health():
    """Proxy chain health check."""
    try:
        result = await health_check.check_proxy_chain()
        return result
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(500, str(e))


@app.get("/api/argocd/status")
async def get_argocd_status():
    """ArgoCD app sync status."""
    try:
        return await argocd_client.get_app_status()
    except Exception as e:
        logger.error(f"ArgoCD status failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/argocd/sync")
async def trigger_argocd_sync():
    """Trigger ArgoCD sync."""
    try:
        return await argocd_client.trigger_sync()
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/bypass/activate")
async def activate_bypass(action: BypassAction):
    """Activate bypass mode (allow all domains) for a given duration."""
    if action.duration_minutes < 1 or action.duration_minutes > 10080:  # max 1 week
        raise HTTPException(400, "Duration must be 1-10080 minutes")
    try:
        content, _ = await gitea_client.get_values_file()
        current_whitelist = gitea_client.parse_whitelist(content)
        await bypass_scheduler.activate_bypass(action.duration_minutes, current_whitelist)
        return {"status": "activated", "duration_minutes": action.duration_minutes,
                "saved_domains": len(current_whitelist)}
    except Exception as e:
        logger.error(f"Bypass activation failed: {e}")
        raise HTTPException(500, str(e))


@app.post("/api/bypass/deactivate")
async def deactivate_bypass():
    """Deactivate bypass mode and restore whitelist."""
    try:
        await bypass_scheduler.deactivate_bypass()
        return {"status": "deactivated"}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.get("/api/bypass/status")
async def get_bypass_status():
    """Get current bypass mode status."""
    return bypass_scheduler.get_state()


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the SPA."""
    index = static_dir / "index.html"
    if index.exists():
        return HTMLResponse(index.read_text())
    return HTMLResponse("<h1>Quarantine ControlCenter</h1><p>Static files not found.</p>")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
