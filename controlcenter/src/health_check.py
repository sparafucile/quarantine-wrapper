"""Proxy chain health check."""
import time
import logging
import httpx
import config
import k8s_client

logger = logging.getLogger(__name__)

# Simple connectivity check URL (returns HTTP 204, no content)
HEALTH_CHECK_URL = "http://clients3.google.com/generate_204"


async def check_proxy_chain() -> dict:
    """Check proxy chain health: pod status + actual proxy connectivity test."""
    results = {"mitmproxy": None, "squid": None, "internet": None, "total_ms": None}

    # 1. Check pod status
    try:
        pods = await k8s_client.get_pods(config.GW_NAMESPACE)
    except Exception as e:
        logger.error(f"Failed to get pods: {e}")
        results["mitmproxy"] = {"ok": False, "error": "Could not fetch pod status"}
        return results

    mitmproxy_running = any(
        p.get("phase") == "Running" and "mitmproxy" in p.get("name", "")
        for p in pods
    )
    squid_running = any(
        p.get("phase") == "Running" and "squid" in p.get("name", "")
        for p in pods
    )

    if not mitmproxy_running:
        results["mitmproxy"] = {"ok": False, "error": "Pod not running"}
        return results

    if not squid_running:
        results["mitmproxy"] = {"ok": True, "ms": 0}
        results["squid"] = {"ok": False, "error": "Pod not running"}
        return results

    # 2. Test mitmproxy API reachability (port 8081)
    #    mitmweb uses ?token= query parameter for auth (NOT Basic Auth!)
    start = time.monotonic()
    params = {}
    if config.MITMPROXY_PASSWORD:
        params["token"] = config.MITMPROXY_PASSWORD
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://{config.MITMPROXY_HOST}:{config.MITMPROXY_API_PORT}/flows",
                params=params,
            )
            if resp.status_code == 403 or resp.status_code == 401:
                results["mitmproxy"] = {"ok": False, "error": f"Auth failed (HTTP {resp.status_code})"}
                results["squid"] = {"ok": squid_running}
                return results
            resp.raise_for_status()
            ms = int((time.monotonic() - start) * 1000)
            results["mitmproxy"] = {"ok": True, "ms": ms}
    except Exception as e:
        results["mitmproxy"] = {"ok": False, "error": f"API: {str(e)[:60]}"}
        results["squid"] = {"ok": squid_running}
        return results

    # 3. Test actual proxy chain: CC -> mitmproxy:8080 -> Squid -> Internet
    # This requires the CC to have egress to mitmproxy proxy port (8080)
    # and the health check URL to be on the Squid whitelist
    proxy_url = f"http://{config.MITMPROXY_HOST}:8080"
    total_start = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy_url, verify=False, timeout=10) as client:
            resp = await client.get(HEALTH_CHECK_URL)
            total_ms = int((time.monotonic() - total_start) * 1000)
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": True, "status": resp.status_code, "ms": total_ms}
            results["total_ms"] = total_ms
    except httpx.ConnectTimeout:
        # CC can't reach mitmproxy:8080 (NetworkPolicy might block it)
        # Fall back to pod-status-only check
        results["squid"] = {"ok": squid_running}
        results["internet"] = {"ok": False, "error": "Proxy timeout (CC hat keinen Egress zu mitmproxy:8080)"}
    except Exception as e:
        err = str(e)[:100]
        if "403" in err or "DENIED" in err:
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": False, "error": f"Squid denied: {err}"}
        else:
            results["squid"] = {"ok": squid_running}
            results["internet"] = {"ok": False, "error": err}

    return results
