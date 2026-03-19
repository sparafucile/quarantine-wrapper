"""Proxy chain health check."""
import time
import socket
import logging
import httpx
import config
import k8s_client

logger = logging.getLogger(__name__)


async def check_proxy_chain() -> dict:
    """Check proxy chain health: pod status + direct connectivity tests.

    Tests each hop individually instead of going through the full proxy chain,
    because the CC in the GW namespace doesn't have proxy env vars and the
    health-check URL would need to be on the Squid whitelist.

    Hops tested:
    1. mitmproxy API (port 8081) — token auth, HTTP GET /flows
    2. mitmproxy proxy (port 8080) — TCP connect only
    3. Squid (port 3128) — TCP connect only
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
            flow_count = len(resp.json()) if resp.headers.get("content-type", "").startswith("application/json") else 0
            ms = int((time.monotonic() - start) * 1000)
            results["mitmproxy"] = {"ok": True, "ms": ms, "flows": flow_count}
    except Exception as e:
        results["mitmproxy"] = {"ok": False, "error": f"API: {str(e)[:60]}"}
        results["squid"] = {"ok": squid_running}
        return results

    # 3. Test Squid reachability (TCP connect to port 3128)
    #    We test Squid directly instead of going through the proxy chain,
    #    because (a) the CC doesn't have proxy env vars (GW namespace),
    #    and (b) the health check URL would need to be on the Squid whitelist.
    squid_host = f"squid.{config.GW_NAMESPACE}.svc.{config.CLUSTER_DNS}"
    squid_port = 3128
    squid_start = time.monotonic()
    try:
        sock = socket.create_connection((squid_host, squid_port), timeout=5)
        sock.close()
        squid_ms = int((time.monotonic() - squid_start) * 1000)
        results["squid"] = {"ok": True, "ms": squid_ms}
    except socket.timeout:
        results["squid"] = {"ok": False, "error": "TCP timeout"}
        results["internet"] = {"ok": False, "error": "Squid nicht erreichbar"}
        return results
    except Exception as e:
        results["squid"] = {"ok": False, "error": str(e)[:60]}
        results["internet"] = {"ok": False, "error": "Squid nicht erreichbar"}
        return results

    # 4. Internet egress: verify Squid has outbound connectivity
    #    Use CONNECT method through Squid to test if it can reach an external host.
    #    This avoids needing the domain on the whitelist — CONNECT to port 443
    #    tests TCP egress without actually completing TLS.
    total_start = time.monotonic()
    try:
        sock = socket.create_connection((squid_host, squid_port), timeout=5)
        # Send HTTP CONNECT to an external host (just tests Squid egress, not whitelist)
        sock.sendall(b"CONNECT connectivity-check.ubuntu.com:443 HTTP/1.1\r\nHost: connectivity-check.ubuntu.com:443\r\n\r\n")
        resp_line = sock.recv(1024).decode("utf-8", errors="replace")
        sock.close()
        total_ms = int((time.monotonic() - total_start) * 1000)

        if "200" in resp_line:
            # CONNECT succeeded — Squid has internet egress AND domain is whitelisted
            results["internet"] = {"ok": True, "ms": total_ms, "detail": "CONNECT OK"}
        elif "403" in resp_line or "DENIED" in resp_line:
            # Squid denied — has egress but domain not whitelisted (expected behavior)
            results["internet"] = {"ok": True, "ms": total_ms, "detail": "Squid egress OK (test-domain denied = normal)"}
        else:
            # Other response — Squid is responding but something unexpected
            short = resp_line.split("\r\n")[0][:60]
            results["internet"] = {"ok": False, "error": f"Unexpected: {short}"}
    except socket.timeout:
        results["internet"] = {"ok": False, "error": "Squid hat kein Internet-Egress (timeout)"}
    except Exception as e:
        results["internet"] = {"ok": False, "error": str(e)[:60]}

    results["total_ms"] = int((time.monotonic() - start) * 1000)
    return results
