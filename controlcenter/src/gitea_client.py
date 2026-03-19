"""ArgoCD-based whitelist management for Squid domain filter."""
import json
import base64
import logging
import httpx
import config

logger = logging.getLogger(__name__)


async def _get_argocd_app() -> dict:
    """Fetch the ArgoCD app spec."""
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}"})
        resp.raise_for_status()
        return resp.json()


async def _put_argocd_app(data: dict):
    """Update the ArgoCD app spec."""
    url = f"{config.ARGOCD_URL}/api/v1/applications/{config.ARGOCD_APP_NAME}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.put(
            url,
            headers={"Cookie": f"argocd.token={config.ARGOCD_TOKEN}", "Content-Type": "application/json"},
            content=json.dumps(data),
        )
        resp.raise_for_status()


async def get_whitelist_from_argocd() -> list[str]:
    """Read current squidAllowedDomains from ArgoCD app (inline values)."""
    try:
        data = await _get_argocd_app()
    except Exception as e:
        logger.error(f"Failed to get ArgoCD app: {e}")
        return []

    helm = data.get("spec", {}).get("source", {}).get("helm", {})

    # Primary source: inline values string
    inline_values = helm.get("values", "")
    if inline_values:
        parsed = _parse_whitelist_yaml(inline_values)
        if parsed:
            logger.info(f"Whitelist from inline values: {len(parsed)} domains")
            return parsed

    # Fallback: parameters array
    domains = []
    for p in helm.get("parameters", []):
        if p.get("name", "").startswith("egress.squidAllowedDomains["):
            domains.append(p["value"])
    if domains:
        logger.info(f"Whitelist from parameters: {len(domains)} domains")
    else:
        logger.warning("No whitelist found")
    return domains


def _parse_whitelist_yaml(content: str) -> list[str]:
    """Extract squidAllowedDomains from YAML content."""
    domains = []
    in_section = False
    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("squidAllowedDomains:"):
            in_section = True
            continue
        if in_section:
            if stripped.startswith("- "):
                domain = stripped[2:].strip()
                if len(domain) >= 2:
                    if (domain[0] == domain[-1]) and domain[0] in ('"', "'"):
                        domain = domain[1:-1]
                if "#" in domain:
                    domain = domain.split("#")[0].strip()
                if domain:
                    domains.append(domain)
            elif stripped and not stripped.startswith("#"):
                break
    return domains


def _rebuild_whitelist_yaml(values_str: str, new_domains: list[str]) -> str:
    """Replace squidAllowedDomains in inline values YAML string."""
    lines = values_str.split("\n")
    result = []
    in_section = False
    replaced = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("squidAllowedDomains:"):
            in_section = True
            replaced = True
            result.append("  squidAllowedDomains:")
            for d in new_domains:
                result.append(f"    - {d}")
            continue
        if in_section:
            if stripped.startswith("- "):
                continue  # Skip old entries
            elif stripped == "" or (stripped and not stripped.startswith("#")):
                in_section = False
                result.append(line)
            else:
                continue  # Skip comments in the section
        else:
            result.append(line)

    return "\n".join(result)


async def add_domain_to_whitelist(domain: str) -> dict:
    """Add a domain by modifying the ArgoCD app inline values."""
    try:
        data = await _get_argocd_app()
        helm = data["spec"]["source"].setdefault("helm", {})
        inline_values = helm.get("values", "")

        current = _parse_whitelist_yaml(inline_values)
        if domain in current:
            return {"status": "exists"}

        current.append(domain)
        helm["values"] = _rebuild_whitelist_yaml(inline_values, current)

        await _put_argocd_app(data)
        logger.info(f"Added domain {domain}, now {len(current)} domains")
        return {"status": "added"}
    except Exception as e:
        logger.error(f"Failed to add domain: {e}")
        raise


async def remove_domain_from_whitelist(domain: str) -> dict:
    """Remove a domain by modifying the ArgoCD app inline values."""
    try:
        data = await _get_argocd_app()
        helm = data["spec"]["source"].setdefault("helm", {})
        inline_values = helm.get("values", "")

        current = _parse_whitelist_yaml(inline_values)
        if domain not in current:
            return {"status": "not_found"}

        current.remove(domain)
        helm["values"] = _rebuild_whitelist_yaml(inline_values, current)

        await _put_argocd_app(data)
        logger.info(f"Removed domain {domain}, now {len(current)} domains")
        return {"status": "removed"}
    except Exception as e:
        logger.error(f"Failed to remove domain: {e}")
        raise
