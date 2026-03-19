"""Proxy chain health check."""
import time
import logging
import httpx
import config

logger = logging.getLogger(__name__)

HEALTH_CHECK_URL = "https://httpbin.org/get"


async def check_proxy_chain() -> dict:
    """Test the full proxy chain: CC → mitmproxy → Squid → Internet."""
    results = {"mitmproxy": None, "squid": None, "internet": None, "total_ms": None}

    proxy_url = f"http://{config.MITMPROXY_HOST}:8080"

    # Test 1: Can we reach mitmproxy?
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"http://{config.MITMPROXY_HOST}:{config.MITMPROXY_API_PORT}/")
            results["mitmproxy"] = {"ok": True, "ms": int((time.monotonic() - start) * 1000)}
    except Exception as e:
        results["mitmproxy"] = {"ok": False, "error": str(e)[:100]}
        return results

    # Test 2: Full chain via proxy
    total_start = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy_url, verify=False, timeout=10) as client:
            resp = await client.get(HEALTH_CHECK_URL)
            total_ms = int((time.monotonic() - total_start) * 1000)
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": True, "status": resp.status_code, "ms": total_ms}
            results["total_ms"] = total_ms
    except httpx.ConnectError as e:
        results["squid"] = {"ok": False, "error": f"Connection failed: {str(e)[:80]}"}
    except httpx.ConnectTimeout:
        results["squid"] = {"ok": False, "error": "Connection timeout"}
    except Exception as e:
        err = str(e)[:100]
        if "403" in err or "DENIED" in err:
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": False, "error": f"Squid denied: {err}"}
        else:
            results["internet"] = {"ok": False, "error": err}

    return results
