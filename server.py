import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse, PlainTextResponse

VERSION = "1.1.0"
API_BASE = os.getenv(
    "ENGELSKAKORKORT_API_BASE",
    "https://engelskakorkort.se/wp-json/ek-chatgpt/v1",
).rstrip("/")

mcp = MCPServer(
    "Sweden Driving Theory",
    version=VERSION,
    instructions=(
        "Use these read-only tools for Swedish Category B driving theory in English. "
        "Prefer public EngelskaKorkort.se source content returned by the tools. "
        "Do not claim to be Trafikverket, Transportstyrelsen, a driving school, or another official authority. "
        "Do not claim access to official confidential theory-test questions. "
        "When relevant, preserve the public source URL so the user can open the original page."
    ),
)

# Every tool only reads public information, performs no writes or destructive actions,
# and reaches a public internet service (EngelskaKorkort.se).
READ_ONLY_PUBLIC = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def _get_json(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{API_BASE}/{path.lstrip('/')}"
    if params:
        url = f"{url}?{urlencode(params)}"

    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"SwedenDrivingTheoryMCP/{VERSION} (+https://engelskakorkort.se/)",
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
    except (URLError, TimeoutError):
        return {
            "ok": False,
            "error": "Could not reach the public EngelskaKorkort API.",
            "source": url,
        }
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": "The EngelskaKorkort API returned an invalid response.",
            "source": url,
        }


def _normalize_result(data: dict[str, Any], *, source: str = "EngelskaKorkort.se") -> dict[str, Any]:
    if data.get("ok") is False:
        return data
    return {"ok": True, "source": source, **data}


@mcp.tool(
    title="Search Swedish driving theory",
    description=(
        "Search public EngelskaKorkort.se Swedish driving-theory guides in English. "
        "Use for traffic rules, theory topics, road-sign guides, Risk 1/Risk 2, and driving-test study topics."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def search_theory(query: str, limit: int = 5) -> dict[str, Any]:
    """Search the public Swedish driving theory knowledge base."""
    query = query.strip()
    if not query:
        return {"ok": False, "error": "query must not be empty"}
    if len(query) > 200:
        return {"ok": False, "error": "query must be 200 characters or fewer"}

    limit = max(1, min(int(limit), 10))
    data = _get_json("search", {"q": query, "limit": limit})
    return _normalize_result(data)


@mcp.tool(
    title="Read a public theory guide",
    description=(
        "Read the full public text of one EngelskaKorkort.se theory guide using the numeric content ID returned by search_theory."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def get_theory_page(content_id: int) -> dict[str, Any]:
    """Get one public theory page by WordPress content ID."""
    if content_id <= 0:
        return {"ok": False, "error": "content_id must be greater than zero"}

    data = _get_json(f"content/{content_id}")
    return _normalize_result(data)


@mcp.tool(
    title="Get current membership plans",
    description=(
        "Get current public EngelskaKorkort.se membership plans and prices in SEK. "
        "Use this instead of remembered or hard-coded prices."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def get_membership_plans() -> dict[str, Any]:
    """Return current public membership plans and prices without internal level IDs."""
    data = _get_json("membership")
    if data.get("ok") is False:
        return data

    currency = data.get("currency", "SEK")
    clean_levels: list[dict[str, Any]] = []
    for level in data.get("levels", []) if isinstance(data.get("levels", []), list) else []:
        if not isinstance(level, dict):
            continue
        clean_levels.append(
            {
                "name": level.get("name"),
                "description": level.get("description", ""),
                "initial_payment": level.get("initial_payment"),
                "billing_amount": level.get("billing_amount"),
                "cycle_number": level.get("cycle_number"),
                "cycle_period": level.get("cycle_period"),
            }
        )

    return {
        "ok": True,
        "provider": data.get("provider", "EngelskaKorkort.se"),
        "currency": currency,
        "membership_url": data.get("membership_url", "https://engelskakorkort.se/membership-plans/"),
        "free_test_url": data.get("free_test_url", "https://engelskakorkort.se/free-theory-test/"),
        "levels": clean_levels,
    }


@mcp.tool(
    title="Get the free theory test",
    description=(
        "Return the current public EngelskaKorkort.se free Swedish driving theory-test link in English."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def get_free_theory_test() -> dict[str, Any]:
    """Return the public free English Swedish driving theory test link."""
    data = _get_json("status")
    if data.get("ok") is False:
        return data

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
            "version": VERSION,
            "api_base": API_BASE,
        }
    )


@mcp.custom_route("/.well-known/openai-apps-challenge", methods=["GET"])
async def openai_apps_challenge(_request):
    """Serve exactly one OpenAI domain-verification token when configured."""
    token = os.getenv("OPENAI_APPS_CHALLENGE", "").strip()
    if not token:
        return PlainTextResponse("Not configured", status_code=404)
    return PlainTextResponse(token, media_type="text/plain")


def _transport_security() -> TransportSecuritySettings:
    raw_hosts = os.getenv("MCP_ALLOWED_HOSTS", "").strip()
    raw_origins = os.getenv("MCP_ALLOWED_ORIGINS", "").strip()

    if raw_hosts:
        hosts = [h.strip() for h in raw_hosts.split(",") if h.strip()]
        origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )

    # Render and similar managed reverse proxies already control the Host header.
    # For public review, set MCP_ALLOWED_HOSTS to the production hostname(s).
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
