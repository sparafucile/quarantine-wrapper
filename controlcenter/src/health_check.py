"""Proxy chain health check."""
import time
import logging
import httpx
import config
import k8s_client

logger = logging.getLogger(__name__)

HEALTH_CHECK_URL = "https://httpbin.org/get"


async def check_proxy_chain() -> dict:
    """Check proxy chain health via pod status and mitmproxy API reachability."""
    results = {"mitmproxy": None, "squid": None, "internet": None, "total_ms": None}

    # Check if pods are running
    try:
        pods = await k8s_client.get_pods(config.GW_NAMESPACE)
    except Exception as e:
        logger.error(f"Failed to get pods in {config.GW_NAMESPACE}: {e}")
        results["mitmproxy"] = {"ok": False, "error": "Could not fetch pod status"}
        return results

    # Check mitmproxy pod is running
    start = time.monotonic()
    mitmproxy_running = any(
        p.get("phase") == "Running" and "mitmproxy" in p.get("name", "")
        for p in pods
    )
    results["mitmproxy"] = {
        "ok": mitmproxy_running,
        "ms": int((time.monotonic() - start) * 1000)
    }
    if not mitmproxy_running:
        results["mitmproxy"]["error"] = "Pod not running"
        return results

    # Check squid pod is running
    squid_running = any(
        p.get("phase") == "Running" and "squid" in p.get("name", "")
        for p in pods
    )
    results["squid"] = {"ok": squid_running}
    if not squid_running:
        results["squid"]["error"] = "Pod not running"
        return results

    # Test mitmproxy API reachability (port 8081)
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://{config.MITMPROXY_HOST}:{config.MITMPROXY_API_PORT}/flows"
            )
            resp.raise_for_status()
            results["mitmproxy"]["ms"] = int((time.monotonic() - start) * 1000)
            results["internet"] = {
                "ok": True,
                "status": "chain healthy (pods running and API reachable)"
            }
    except Exception as e:
        results["internet"] = {
            "ok": False,
            "error": f"mitmproxy API unreachable: {str(e)[:80]}"
        }

    return results
