"""mitmweb REST API client for traffic inspection."""
import logging
import httpx
import config

logger = logging.getLogger(__name__)


async def get_flows(limit: int = 100) -> list[dict]:
    """Get recent flows from mitmweb API."""
    url = f"http://{config.MITMPROXY_HOST}:{config.MITMPROXY_API_PORT}/flows"
    
    # mitmweb auth: try token as query param, then basic auth, then no auth
    headers = {}
    params = {}
    if config.MITMPROXY_PASSWORD:
        # mitmweb with --set web_password uses token-based auth
        params["token"] = config.MITMPROXY_PASSWORD

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 401 or resp.status_code == 403:
                # Try basic auth as fallback
                auth = httpx.BasicAuth(username="", password=config.MITMPROXY_PASSWORD)
                resp = await client.get(url, auth=auth)
            resp.raise_for_status()
            flows = resp.json()

            result = []
            for f in flows[-limit:]:
                req = f.get("request", {})
                resp_data = f.get("response", {})
                result.append({
                    "id": f.get("id", ""),
                    "timestamp": req.get("timestamp_start", 0),
                    "method": req.get("method", ""),
                    "host": req.get("pretty_host", req.get("host", "")),
                    "path": req.get("path", ""),
                    "status_code": resp_data.get("status_code", 0),
                    "size": resp_data.get("content_length", 0) or 0,
                    "error": f.get("error", {}).get("msg", "") if isinstance(f.get("error"), dict) else str(f.get("error", "")),
                })
            return result
    except Exception as e:
        logger.warning(f"mitmproxy API error: {e}")
        return []
