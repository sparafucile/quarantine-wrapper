"""Timed bypass mode for Squid domain filter."""
import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Optional
import config
import k8s_client

logger = logging.getLogger(__name__)

# In-memory state (also persisted to cc-state ConfigMap)
_bypass_state = {
    "active": False,
    "expires_at": None,       # ISO timestamp
    "saved_whitelist": [],    # Domains to restore
    "mode": None,             # "timed", "nightly", "weekend"
}


def get_state() -> dict:
    return dict(_bypass_state)


async def _save_state():
    """Persist bypass state to ConfigMap."""
    try:
        cm = await k8s_client.get_configmap(config.GW_NAMESPACE, config.CC_STATE_CM)
        data = {"bypass-state": json.dumps(_bypass_state)}
        if cm:
            await k8s_client.patch_configmap(config.GW_NAMESPACE, config.CC_STATE_CM, data)
        else:
            # Create ConfigMap
            import httpx
            url = f"{config.K8S_API_URL}/api/v1/namespaces/{config.GW_NAMESPACE}/configmaps"
            with open(config.K8S_TOKEN_PATH) as f:
                token = f.read().strip()
            async with httpx.AsyncClient(verify=config.K8S_CA_PATH, timeout=10) as client:
                await client.post(url, headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                }, content=json.dumps({
                    "apiVersion": "v1", "kind": "ConfigMap",
                    "metadata": {"name": config.CC_STATE_CM, "namespace": config.GW_NAMESPACE},
                    "data": data,
                }))
    except Exception as e:
        logger.warning(f"Failed to save bypass state: {e}")


async def _load_state():
    """Load bypass state from ConfigMap on startup."""
    global _bypass_state
    try:
        cm = await k8s_client.get_configmap(config.GW_NAMESPACE, config.CC_STATE_CM)
        if cm and "bypass-state" in cm.get("data", {}):
            saved = json.loads(cm["data"]["bypass-state"])
            _bypass_state.update(saved)
            # Check if expired
            if _bypass_state["active"] and _bypass_state["expires_at"]:
                exp = datetime.fromisoformat(_bypass_state["expires_at"])
                if datetime.now() >= exp:
                    logger.info("Bypass expired during downtime, restoring whitelist")
                    await deactivate_bypass()
    except Exception as e:
        logger.warning(f"Failed to load bypass state: {e}")


async def _patch_squid_configmap(domains: list[str]):
    """Patch the Squid ConfigMap with new domain list and restart Squid pod."""
    # Read current squid config
    cm = await k8s_client.get_configmap(config.GW_NAMESPACE, "squid-config")
    if not cm:
        logger.error("squid-config ConfigMap not found")
        return

    squid_conf = cm.get("data", {}).get("squid.conf", "")

    if domains:
        # Build ACL lines
        acl_lines = "\n".join(f".{d}" for d in domains)
        # Replace or inject the whitelist ACL
        # The squid.conf template has a pattern we can match
        new_conf = _replace_acl_in_squid_conf(squid_conf, acl_lines)
    else:
        # Empty domains = allow all (remove ACL deny rule)
        new_conf = _remove_acl_from_squid_conf(squid_conf)

    await k8s_client.patch_configmap(config.GW_NAMESPACE, "squid-config", {"squid.conf": new_conf})

    # Restart squid pod
    pods = await k8s_client.get_pods(config.GW_NAMESPACE)
    for p in pods:
        if "squid" in p["name"] and p["phase"] == "Running":
            await k8s_client.k8s_delete(f"/api/v1/namespaces/{config.GW_NAMESPACE}/pods/{p['name']}")
            logger.info(f"Restarted squid pod: {p['name']}")
            break


def _replace_acl_in_squid_conf(conf: str, acl_lines: str) -> str:
    """Replace the allowed_domains ACL content in squid.conf."""
    # This is a simplified approach — the actual squid.conf structure
    # depends on how the Helm template generates it
    lines = conf.split("\n")
    result = []
    in_acl = False
    for line in lines:
        if "acl allowed_domains" in line and "dstdomain" in line:
            in_acl = True
            result.append(f"acl allowed_domains dstdomain {acl_lines.replace(chr(10), ' ')}")
            continue
        if in_acl and line.strip().startswith("."):
            continue  # Skip old domain lines
        else:
            in_acl = False
        result.append(line)
    return "\n".join(result)


def _remove_acl_from_squid_conf(conf: str) -> str:
    """Remove domain restrictions from squid.conf (allow all)."""
    lines = conf.split("\n")
    result = []
    for line in lines:
        # Comment out the deny rule for non-whitelisted domains
        if "http_access deny" in line and "allowed_domains" in line:
            result.append(f"# BYPASS: {line}")
        else:
            result.append(line)
    return "\n".join(result)


async def activate_bypass(duration_minutes: int, current_whitelist: list[str]):
    """Activate bypass mode for a given duration."""
    global _bypass_state
    _bypass_state = {
        "active": True,
        "expires_at": (datetime.now() + timedelta(minutes=duration_minutes)).isoformat(),
        "saved_whitelist": current_whitelist,
        "mode": "timed",
    }
    await _save_state()
    await _patch_squid_configmap([])  # Empty = allow all
    logger.info(f"Bypass activated for {duration_minutes}min, saved {len(current_whitelist)} domains")

    # Schedule deactivation
    asyncio.create_task(_bypass_timer(duration_minutes * 60))


async def deactivate_bypass():
    """Deactivate bypass mode and restore saved whitelist."""
    global _bypass_state
    saved = _bypass_state.get("saved_whitelist", [])
    _bypass_state = {"active": False, "expires_at": None, "saved_whitelist": [], "mode": None}
    await _save_state()
    if saved:
        await _patch_squid_configmap(saved)
        logger.info(f"Bypass deactivated, restored {len(saved)} domains")
    else:
        logger.info("Bypass deactivated, no domains to restore")


async def _bypass_timer(seconds: float):
    """Background task that deactivates bypass after timeout."""
    await asyncio.sleep(seconds)
    if _bypass_state["active"]:
        logger.info("Bypass timer expired, restoring whitelist")
        await deactivate_bypass()


async def init():
    """Initialize bypass scheduler on startup."""
    await _load_state()
    if _bypass_state["active"] and _bypass_state["expires_at"]:
        exp = datetime.fromisoformat(_bypass_state["expires_at"])
        remaining = (exp - datetime.now()).total_seconds()
        if remaining > 0:
            logger.info(f"Resuming bypass timer: {int(remaining)}s remaining")
            asyncio.create_task(_bypass_timer(remaining))
        else:
            await deactivate_bypass()
