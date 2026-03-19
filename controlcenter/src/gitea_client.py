"""ArgoCD-based whitelist management for Squid domain filter."""
import json
import base64
import logging
import httpx
import config

logger = logging.getLogger(__name__)


async def get_whitelist_from_argocd() -> list[str]:
    """Read current squidAllowedDomains from ArgoCD app.
    
    Checks multiple sources in order:
    1. ArgoCD Helm parameters (egress.squidAllowedDomains[N])
    2. valueFiles referenced in the app (read from Gitea)
    3. Rendered Squid ConfigMap in the cluster (fallback)
    """
    try:
        url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.error(f"Failed to get ArgoCD app: {e}")
        return []

    helm = data.get("spec", {}).get("source", {}).get("helm", {})

    # 1. Check parameters array for explicit domain entries
    domains = []
    for p in helm.get("parameters", []):
        name = p.get("name", "")
        if name.startswith("egress.squidAllowedDomains["):
            domains.append(p["value"])
    
    if domains:
        logger.info(f"Whitelist from ArgoCD parameters: {len(domains)} domains")
        return domains

    # 2. Check valueFiles (read from Gitea)
    for vf in helm.get("valueFiles", []):
        try:
            content = await _read_gitea_file(vf)
            parsed = _parse_whitelist_yaml(content)
            if parsed:
                logger.info(f"Whitelist from {vf}: {len(parsed)} domains")
                return parsed
        except Exception as e:
            logger.warning(f"Failed to read valueFile {vf}: {e}")

    logger.warning("No whitelist found in ArgoCD parameters or valueFiles")
    return []


async def _read_gitea_file(path: str) -> str:
    """Read a file from the wrapper Gitea repo."""
    url = f"{config.GITEA_URL}/api/v1/repos/{config.GITEA_REPO}/contents/{path}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Authorization": f"token {config.GITEA_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
        return base64.b64decode(data["content"]).decode()


def _parse_whitelist_yaml(content: str) -> list[str]:
    """Extract squidAllowedDomains from YAML content (simple parser)."""
    domains = []
    in_section = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("squidAllowedDomains:"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                domain = stripped[2:].strip().strip(\"\'\").strip("\'")
                if "#" in domain:
                    domain = domain.split("#")[0].strip()
                if domain:
                    domains.append(domain)
            elif stripped and not stripped.startswith("#"):
                break
    return domains


async def add_domain_to_whitelist(domain: str) -> dict:
    """Add a domain to the whitelist via ArgoCD Helm parameters."""
    try:
        url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
            resp.raise_for_status()
            data = resp.json()

        helm = data["spec"]["source"].setdefault("helm", {})
        params = helm.setdefault("parameters", [])
        
        # Get existing domains from parameters
        domain_params = [p for p in params if p["name"].startswith("egress.squidAllowedDomains[")]
        current_domains = [p["value"] for p in domain_params]
        
        if domain in current_domains:
            return {"status": "exists"}
        
        new_index = len(current_domains)
        params.append({"name": f"egress.squidAllowedDomains[{new_index}]", "value": domain})
        
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.put(
                url,
                headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}", "Content-Type": "application/json"},
                content=json.dumps(data),
            )
            resp.raise_for_status()
        
        return {"status": "added"}
    except Exception as e:
        logger.error(f"Failed to add domain: {e}")
        raise


async def remove_domain_from_whitelist(domain: str) -> dict:
    """Remove a domain from the whitelist via ArgoCD Helm parameters."""
    try:
        url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
            resp.raise_for_status()
            data = resp.json()

        helm = data["spec"]["source"].setdefault("helm", {})
        params = helm.setdefault("parameters", [])
        
        domain_params = [(i, p) for i, p in enumerate(params) if p["name"].startswith("egress.squidAllowedDomains[")]
        current_domains = [p["value"] for _, p in domain_params]
        
        if domain not in current_domains:
            return {"status": "not_found"}
        
        current_domains.remove(domain)
        params[:] = [p for p in params if not p["name"].startswith("egress.squidAllowedDomains[")]
        for i, d in enumerate(current_domains):
            params.append({"name": f"egress.squidAllowedDomains[{i}]", "value": d})
        
        async with httpx.AsyncClient(verify=False, timeout=10) as client:
            resp = await client.put(
                url,
                headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}", "Content-Type": "application/json"},
                content=json.dumps(data),
            )
            resp.raise_for_status()
        
        return {"status": "removed"}
    except Exception as e:
        logger.error(f"Failed to remove domain: {e}")
        raise
