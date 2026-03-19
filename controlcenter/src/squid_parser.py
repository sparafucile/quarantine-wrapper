"""Parse Squid access logs for denied domains."""
import re
import logging
from datetime import datetime
import config
import k8s_client

logger = logging.getLogger(__name__)

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


async def get_denied_domains(tail_lines: int = 500) -> list[dict]:
    """Get denied domains from Squid pod logs."""
    # Find squid pod
    pods = await k8s_client.get_pods(config.GW_NAMESPACE)
    squid_pod = None
    for p in pods:
        if "squid" in p["name"] and p["phase"] == "Running":
            squid_pod = p["name"]
            break

    if not squid_pod:
        logger.warning("No running squid pod found")
        return []

    try:
        logs = await k8s_client.get_pod_logs(config.GW_NAMESPACE, squid_pod, tail_lines)
    except Exception as e:
        logger.warning(f"Failed to read squid logs: {e}")
        return []

    denied = []
    seen_domains = set()
    for line in logs.split("\n"):
        if not line.strip():
            continue
        parsed = parse_log_line(line)
        if parsed and "DENIED" in parsed["action"]:
            # Deduplicate by domain
            if parsed["domain"] not in seen_domains:
                seen_domains.add(parsed["domain"])
            denied.append(parsed)

    return denied
