"""Parse Squid access logs for denied domains with persistent cache."""
import re
import json
import logging
from datetime import datetime
import config
import k8s_client

logger = logging.getLogger(__name__)

# In-memory cache of denied entries (survives squid pod restarts)
_denied_cache: list[dict] = []
_MAX_CACHE = 1000

# Squid log format: timestamp elapsed client action/code size method url ident hierarchy/from content-type
# Example: 1710783600.123    0 10.244.1.50 TCP_DENIED/403 3900 CONNECT api.example.com:443 - HIER_NONE/- text/html
SQUID_LOG_RE = re.compile(
    r"(?P<timestamp>[\d.]+)\s+"
    r"(?P<elapsed>\d+)\s+"
    r"(?P<client>\S+)\s+"
    r"(?P<action>\S+)\s+"
    r"(?P<size>\d+)\s+"
    r"(?P<method>\S+)\s+"
    r"(?P<url>\S+)\s+"
    r"(?P<ident>\S+)\s+"
    r"(?P<hierarchy>\S+)\s+"
    r"(?P<content_type>\S+)"
)


def parse_log_line(line: str) -> dict | None:
    """Parse a single Squid access log line."""
    m = SQUID_LOG_RE.match(line.strip())
    if not m:
        return None
    g = m.groupdict()
    try:
        ts = datetime.fromtimestamp(float(g["timestamp"]))
    except (ValueError, OSError):
        ts = None

    # Extract domain from URL (CONNECT domain:port or http://domain/path)
    url = g["url"]
    domain = url.split(":")[0] if ":" in url and "//" not in url else url.split("/")[2] if "//" in url else url

    return {
        "timestamp": ts.isoformat() if ts else g["timestamp"],
        "client": g["client"],
        "action": g["action"],
        "method": g["method"],
        "domain": domain,
        "url": url,
        "size": int(g["size"]),
    }


async def _load_cache():
    """Load denied cache from cc-state ConfigMap on startup."""
    global _denied_cache
    try:
        cm = await k8s_client.get_configmap(config.GW_NAMESPACE, config.CC_STATE_CM)
        if cm and "denied-cache" in cm.get("data", {}):
            _denied_cache = json.loads(cm["data"]["denied-cache"])
            logger.info(f"Loaded {len(_denied_cache)} cached denied entries")
    except Exception as e:
        logger.warning(f"Failed to load denied cache: {e}")


async def _save_cache():
    """Persist denied cache to cc-state ConfigMap."""
    try:
        cm = await k8s_client.get_configmap(config.GW_NAMESPACE, config.CC_STATE_CM)
        data = {"denied-cache": json.dumps(_denied_cache[-_MAX_CACHE:])}
        if cm:
            await k8s_client.patch_configmap(config.GW_NAMESPACE, config.CC_STATE_CM, data)
        else:
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
        logger.warning(f"Failed to save denied cache: {e}")


async def get_denied_domains(tail_lines: int = 500) -> list[dict]:
    """Get denied domains from Squid pod logs + persistent cache."""
    global _denied_cache

    # Find squid pod
    pods = await k8s_client.get_pods(config.GW_NAMESPACE)
    squid_pod = None
    for p in pods:
        if "squid" in p["name"] and p["phase"] == "Running":
            squid_pod = p["name"]
            break

    new_from_logs = []
    if squid_pod:
        try:
            logs = await k8s_client.get_pod_logs(config.GW_NAMESPACE, squid_pod, tail_lines)
            for line in logs.split("\n"):
                if not line.strip():
                    continue
                parsed = parse_log_line(line)
                if parsed and "DENIED" in parsed["action"]:
                    new_from_logs.append(parsed)
        except Exception as e:
            logger.warning(f"Failed to read squid logs: {e}")
    else:
        logger.warning("No running squid pod found")

    # Merge new entries into cache (deduplicate by domain+timestamp)
    existing_keys = set(d["domain"] + "|" + d["timestamp"] for d in _denied_cache)
    added = 0
    for entry in new_from_logs:
        key = entry["domain"] + "|" + entry["timestamp"]
        if key not in existing_keys:
            _denied_cache.append(entry)
            existing_keys.add(key)
            added += 1

    # Trim cache
    if len(_denied_cache) > _MAX_CACHE:
        _denied_cache = _denied_cache[-_MAX_CACHE:]

    # Persist if new entries were added
    if added > 0:
        await _save_cache()

    return _denied_cache
