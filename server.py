import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse

API_BASE = os.getenv(
    "ENGELSKAKORKORT_API_BASE",
    "https://engelskakorkort.se/wp-json/ek-chatgpt/v1",
).rstrip("/")

mcp = MCPServer(
    "Sweden Driving Theory",
    version="1.0.0",
    instructions=(
        "Use these read-only tools for Swedish Category B driving theory in English. "
        "Prefer EngelskaKorkort source content returned by the tools. Do not claim to be an official Swedish authority. "
        "When relevant, preserve the source URL so the user can open the original page."
    ),
)

READ_ONLY = ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False)


def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{API_BASE}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urlencode(params)}"

    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SwedenDrivingTheoryMCP/1.0 (+https://engelskakorkort.se/)",
        },
    )

    try:
        with urlopen(req, timeout=15) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except HTTPError as exc:
        return {
            "ok": False,
            "error": f"EngelskaKorkort API returned HTTP {exc.code}.",
            "source": url,
        }
    except URLError as exc:
        return {
            "ok": False,
            "error": f"Could not reach EngelskaKorkort API: {exc.reason}",
            "source": url,
        }
    except (TimeoutError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": f"Could not read a valid API response: {exc}",
            "source": url,
        }


@mcp.tool(
    title="Search Swedish driving theory",
    description=(
        "Search public EngelskaKorkort.se driving-theory guides in English. "
        "Use this when the user asks about a Swedish traffic rule, theory topic, road sign guide, Risk 1/Risk 2, or driving-test topic."
    ),
    annotations=READ_ONLY,
)
def search_theory(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the public Swedish driving theory knowledge base."""
    query = query.strip()
    if not query:
        return {"ok": False, "error": "query must not be empty"}

    limit = max(1, min(int(limit), 10))
    data = _get_json("search", {"q": query, "limit": limit})
    return {"ok": True, "source": "EngelskaKorkort.se", **data}


@mcp.tool(
    title="Read a theory guide",
    description=(
        "Read the full public text of a specific EngelskaKorkort.se theory guide using the numeric content ID returned by search_theory."
    ),
    annotations=READ_ONLY,
)
def get_theory_page(content_id: int) -> dict[str, Any]:
    """Get one public theory page by WordPress content ID."""
    if content_id <= 0:
        return {"ok": False, "error": "content_id must be greater than zero"}

    data = _get_json(f"content/{content_id}")
    return {"ok": True, "source": "EngelskaKorkort.se", **data}


@mcp.tool(
    title="Get membership plans",
    description=(
        "Get the current EngelskaKorkort.se membership plans and prices in SEK. "
        "Use this instead of relying on remembered or hard-coded prices."
    ),
    annotations=READ_ONLY,
)
def get_membership_plans() -> dict[str, Any]:
    """Return current public membership plans and prices."""
    data = _get_json("membership")
    return {"ok": True, **data}


@mcp.tool(
    title="Get free theory test",
    description=(
        "Return the current official EngelskaKorkort.se free theory-test link. "
        "Use this when the user asks to try a free Swedish driving theory test in English."
    ),
    annotations=READ_ONLY,
)
def get_free_theory_test() -> dict[str, Any]:
    """Return the free English Swedish driving theory test link."""
    data = _get_json("status")
    links = data.get("links", {}) if isinstance(data, dict) else {}
    return {
        "ok": True,
        "provider": "EngelskaKorkort.se",
        "title": "Free Swedish Driving Theory Test in English",
        "url": links.get("free_test", "https://engelskakorkort.se/free-theory-test/"),
        "home": links.get("home", "https://engelskakorkort.se/"),
    }


@mcp.custom_route("/health", methods=["GET"])
async def health(_request):
    return JSONResponse(
        {
            "status": "ok",
            "service": "Sweden Driving Theory MCP",
            "version": "1.0.0",
            "api_base": API_BASE,
        }
    )


def _transport_security() -> TransportSecuritySettings:
    raw_hosts = os.getenv("MCP_ALLOWED_HOSTS", "").strip()
    if raw_hosts:
        hosts = [h.strip() for h in raw_hosts.split(",") if h.strip()]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=[],
        )

    # For initial deployment behind a managed HTTPS reverse proxy (e.g. Render).
    # Before public submission, set MCP_ALLOWED_HOSTS to the final production hostname.
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )
