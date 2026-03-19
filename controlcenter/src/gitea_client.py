"""Gitea API client for GitOps whitelist management."""
import json
import base64
import logging
import httpx
import config

logger = logging.getLogger(__name__)


async def get_values_file() -> tuple[str, str]:
    """Read the values file from Gitea. Returns (content, sha)."""
    url = f"{config.GITEA_URL}/api/v1/repos/{config.GITEA_REPO}/contents/{config.GITEA_VALUES_FILE}"
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.get(url, headers={"Authorization": f"token {config.GITEA_TOKEN}"})
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"]).decode()
        return content, data["sha"]


async def update_values_file(content: str, sha: str, message: str) -> dict:
    """Update the values file in Gitea."""
    url = f"{config.GITEA_URL}/api/v1/repos/{config.GITEA_REPO}/contents/{config.GITEA_VALUES_FILE}"
    encoded = base64.b64encode(content.encode()).decode()
    async with httpx.AsyncClient(verify=False, timeout=10) as client:
        resp = await client.put(
            url,
            headers={"Authorization": f"token {config.GITEA_TOKEN}", "Content-Type": "application/json"},
            content=json.dumps({"message": message, "content": encoded, "sha": sha}),
        )
        resp.raise_for_status()
        return resp.json()


def parse_whitelist(yaml_content: str) -> list[str]:
    """Extract squidAllowedDomains from YAML content (simple parser, no PyYAML needed)."""
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
                # Remove inline comments
                if "#" in domain:
                    domain = domain.split("#")[0].strip()
                if domain:
                    domains.append(domain)
            elif stripped and not stripped.startswith("#"):
                break  # End of list
    return domains


def update_whitelist(yaml_content: str, new_domains: list[str]) -> str:
    """Replace squidAllowedDomains in YAML content."""
    lines = yaml_content.split("\n")
    result = []
    in_squid_section = False
    replaced = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("squidAllowedDomains:"):
            in_squid_section = True
            replaced = True
            result.append("  squidAllowedDomains:")
            for domain in new_domains:
                result.append(f"    - {domain}")
            continue
        if in_squid_section:
            if stripped.startswith("- "):
                continue  # Skip old entries
            elif stripped and not stripped.startswith("#"):
                in_squid_section = False
                result.append(line)
            else:
                if not stripped:
                    in_squid_section = False
                    result.append(line)
                continue
        else:
            result.append(line)

    return "\n".join(result)
