"""ArgoCD-based whitelist management for Squid allowed domains."""
import json
import base64
import logging
import httpx
import config

logger = logging.getLogger(__name__)


async def get_whitelist_from_argocd() -> list[str]:
    """Read current squidAllowedDomains from ArgoCD app Helm parameters."""
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
    
    # Extract squidAllowedDomains from Helm parameters or valuesObject
    helm = data.get("spec", {}).get("source", {}).get("helm", {})
    
    # Check parameters array
    domains = []
    for p in helm.get("parameters", []):
        name = p.get("name", "")
        if name.startswith("egress.squidAllowedDomains["):
            domains.append(p["value"])
    
    # Also check valueFiles content (rendered values)
    # If domains found in parameters, return those
    if domains:
        return domains
    
    # Fallback: check if values file has the domains
    value_files = helm.get("valueFiles", [])
    if value_files:
        for vf in value_files:
            try:
                content, _ = await _get_gitea_file(vf)
                return parse_whitelist_from_yaml(content)
            except Exception:
                continue
    
    return domains


async def _get_gitea_file(path: str) -> tuple[str, str]:
    """Read a file from Gitea. Returns (content, sha)."""
    url = f"{config.GITEA_URL}/api/v1/repos/{config.GITEA_REPO}/contents/{path}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Authorization": f"token {config.GITEA_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"]).decode()
        return content, data["sha"]


def parse_whitelist_from_yaml(yaml_content: str) -> list[str]:
    """Extract squidAllowedDomains from YAML content."""
    domains = []
    in_squid_section = False
    for line in yaml_content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("squidAllowedDomains:"):
            in_squid_section = True
            continue
        if in_squid_section:
            if stripped.startswith("- "):
                domain = stripped[2:].strip().strip('"').strip("'")
                if "#" in domain:
                    domain = domain.split("#")[0].strip()
                if domain:
                    domains.append(domain)
            elif stripped and not stripped.startswith("#"):
                break
    return domains


async def add_domain_to_argocd(domain: str) -> dict:
    """Add a domain to the ArgoCD app's Helm parameters."""
    # GET current app
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
    
    # Get current domains from parameters
    helm = data["spec"]["source"].setdefault("helm", {})
    params = helm.setdefault("parameters", [])
    
    # Find existing domain parameters
    domain_params = [p for p in params if p["name"].startswith("egress.squidAllowedDomains[")]
    current_domains = [p["value"] for p in domain_params]
    
    if domain in current_domains:
        return {"status": "exists"}
    
    # Add new domain
    new_index = len(current_domains)
    params.append({"name": f"egress.squidAllowedDomains[{new_index}]", "value": domain})
    
    # PUT back
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.put(
            url,
            headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}", "Content-Type": "application/json"},
            content=json.dumps(data),
        )
        resp.raise_for_status()
    
    return {"status": "added"}


async def remove_domain_from_argocd(domain: str) -> dict:
    """Remove a domain from the ArgoCD app's Helm parameters."""
    # GET current app
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
    
    helm = data["spec"]["source"].setdefault("helm", {})
    params = helm.setdefault("parameters", [])
    
    # Remove domain and re-index
    domain_params = [(i, p) for i, p in enumerate(params) if p["name"].startswith("egress.squidAllowedDomains[")]
    current_domains = [p["value"] for _, p in domain_params]
    
    if domain not in current_domains:
        return {"status": "not_found"}
    
    current_domains.remove(domain)
    
    # Remove all old domain params
    params[:] = [p for p in params if not p["name"].startswith("egress.squidAllowedDomains[")]
    
    # Re-add with correct indices
    for i, d in enumerate(current_domains):
        params.append({"name": f"egress.squidAllowedDomains[{i}]", "value": d})
    
    # PUT back
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.put(
            url,
            headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}", "Content-Type": "application/json"},
            content=json.dumps(data),
        )
        resp.raise_for_status()
    
    return {"status": "removed"}
