"""Proxy chain health check — tests the full CC -> mitmproxy -> Squid -> Internet chain."""
import time
import socket
import logging
import httpx
import config
import k8s_client

logger = logging.getLogger(__name__)

# Health-check URL: HTTP 204, no content, fast — must be on Squid whitelist!
HEALTH_CHECK_URL = "http://clients3.google.com/generate_204"

# CA cert path (set by SSL_CERT_FILE env var if mitmproxy CA is installed)
CA_CERT_PATH = "/etc/ssl/custom/ca-certificates.crt"


def _get_proxy_url() -> str:
    """Get the mitmproxy proxy URL (from env or construct from config)."""
    import os
    return os.getenv("PROXY_URL", f"http://{config.MITMPROXY_HOST}:8080")


async def check_proxy_chain() -> dict:
    """Check full proxy chain: CC -> mitmproxy:8080 -> Squid:3128 -> Internet.

    Tests:
    1. Pod status (mitmproxy + squid running?)
    2. mitmproxy API (:8081) — token auth, flow count
    3. Full proxy chain — HTTP request through mitmproxy:8080 to internet
    4. If chain fails: individual hop diagnostics (TCP to each component)
    """
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

    # 2. Test mitmproxy API (port 8081) — token auth
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
            if resp.status_code in (401, 403):
                results["mitmproxy"] = {"ok": False, "error": f"Auth failed (HTTP {resp.status_code})"}
                results["squid"] = {"ok": squid_running}
                return results
            resp.raise_for_status()
            flow_count = 0
            try:
                flow_count = len(resp.json())
            except Exception:
                pass
            ms = int((time.monotonic() - start) * 1000)
            results["mitmproxy"] = {"ok": True, "ms": ms, "flows": flow_count}
    except Exception as e:
        results["mitmproxy"] = {"ok": False, "error": f"API: {str(e)[:60]}"}
        results["squid"] = {"ok": squid_running}
        return results

    # 3. Full proxy chain test: CC -> mitmproxy:8080 -> Squid -> Internet
    import os
    proxy_url = _get_proxy_url()
    ca_path = CA_CERT_PATH if os.path.exists(CA_CERT_PATH) else False

    total_start = time.monotonic()
    try:
        async with httpx.AsyncClient(proxy=proxy_url, verify=ca_path, timeout=10) as client:
            resp = await client.get(HEALTH_CHECK_URL)
            total_ms = int((time.monotonic() - total_start) * 1000)
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": True, "status": resp.status_code, "ms": total_ms}
            results["total_ms"] = total_ms
    except httpx.ConnectTimeout:
        # TCP to mitmproxy:8080 failed — run diagnostics
        results["squid"], results["internet"] = _diagnose_chain_failure(squid_running)
    except httpx.ConnectError as e:
        err = str(e)[:100]
        results["squid"], results["internet"] = _diagnose_chain_failure(squid_running, err)
    except Exception as e:
        err = str(e)[:100]
        if "403" in err or "DENIED" in err:
            # Squid denied the domain (domain not on whitelist)
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": False, "error": f"Squid denied: {err[:60]}"}
        elif "SSL" in err or "certificate" in err.lower():
            results["squid"] = {"ok": True}
            results["internet"] = {"ok": False, "error": f"TLS/CA-Fehler: {err[:60]}"}
        else:
            results["squid"] = {"ok": squid_running}
            results["internet"] = {"ok": False, "error": err[:60]}

    return results


def _diagnose_chain_failure(squid_running: bool, error: str = "") -> tuple[dict, dict]:
    """When the full chain fails, test individual TCP hops for diagnostics."""
    squid_host = f"squid.{config.GW_NAMESPACE}.svc.{config.CLUSTER_DNS}"
    proxy_host = config.MITMPROXY_HOST

    # Test TCP to mitmproxy:8080
    mitmproxy_tcp = _tcp_check(proxy_host, 8080)
    if not mitmproxy_tcp:
        return (
            {"ok": squid_running},
            {"ok": False, "error": "CC kann mitmproxy:8080 nicht erreichen (NetworkPolicy/CiliumNP?)"},
        )

    # Test TCP to Squid:3128
    squid_tcp = _tcp_check(squid_host, 3128)
    if not squid_tcp:
        return (
            {"ok": False, "error": "Squid:3128 nicht erreichbar"},
            {"ok": False, "error": "Squid nicht erreichbar"},
        )

    # Both hops OK but chain still failed
    detail = f"Proxy-Kette fehlgeschlagen trotz TCP-OK ({error[:40]})" if error else "Proxy-Kette timeout (mitmproxy→squid→internet)"
    return (
        {"ok": True},
        {"ok": False, "error": detail},
    )


def _tcp_check(host: str, port: int, timeout: float = 3) -> bool:
    """Quick TCP connectivity check."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except Exception:
        return False
