import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import JSONResponse, PlainTextResponse


VERSION = "1.2.0"

API_BASE = os.getenv(
    "ENGELSKAKORKORT_API_BASE",
    "https://engelskakorkort.se/wp-json/ek-chatgpt/v1",
).rstrip("/")


# Pages related to purchasing, memberships, accounts or checkout are intentionally
# excluded from the public ChatGPT Plugin tools.
BLOCKED_PATH_FRAGMENTS = (
    "/membership",
    "/checkout",
    "/account",
    "/login",
    "/register",
    "/cart",
    "/payment",
    "/order",
    "/wp-login",
)


mcp = MCPServer(
    "Sweden Driving Theory",
    version=VERSION,
    instructions=(
        "Use these read-only tools for Swedish Category B driving theory in English. "
        "Prefer public educational content returned by EngelskaKorkort.se. "
        "Do not claim to be Trafikverket, Transportstyrelsen, a driving school, "
        "or another official authority. "
        "Do not claim access to official or confidential Swedish theory-test questions. "
        "Do not promote, list, or direct users to paid memberships, subscriptions, "
        "checkout pages, account upgrades, or digital-content purchases. "
        "When relevant, preserve the public source URL so the user can open "
        "the original educational page."
    ),
)


# All exposed tools are read-only. They do not create, modify or delete data.
READ_ONLY_PUBLIC = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def _get_json(
    path: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Fetch JSON from the public EngelskaKorkort.se WordPress REST API.
    """

    url = f"{API_BASE}/{path.lstrip('/')}"

    if params:
        url = f"{url}?{urlencode(params)}"

    req = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": (
                f"SwedenDrivingTheoryMCP/{VERSION} "
                "(+https://engelskakorkort.se/)"
            ),
        },
    )

    try:
        with urlopen(req, timeout=15) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)

    except HTTPError as exc:
        return {
            "ok": False,
            "error": (
                f"EngelskaKorkort API returned HTTP {exc.code}."
            ),
            "source": url,
        }

    except (URLError, TimeoutError):
        return {
            "ok": False,
            "error": (
                "Could not reach the public EngelskaKorkort API."
            ),
            "source": url,
        }

    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": (
                "The EngelskaKorkort API returned an invalid response."
            ),
            "source": url,
        }


def _normalize_result(
    data: dict[str, Any],
    *,
    source: str = "EngelskaKorkort.se",
) -> dict[str, Any]:
    """
    Add a stable success flag and source label to successful responses.
    """

    if data.get("ok") is False:
        return data

    return {
        "ok": True,
        "source": source,
        **data,
    }


def _is_allowed_public_url(url: str | None) -> bool:
    """
    Return True only for URLs that are suitable for the public educational
    Plugin surface.

    Membership, checkout, login, account and purchasing-related pages
    are intentionally excluded.
    """

    if not url:
        return True

    try:
        parsed = urlparse(str(url))
        path = parsed.path.lower()
    except Exception:
        return False

    for fragment in BLOCKED_PATH_FRAGMENTS:
        if fragment in path:
            return False

    return True


def _filter_search_results(
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Remove commercial/account-related pages from WordPress search results.
    """

    if data.get("ok") is False:
        return data

    items = data.get("items")

    if not isinstance(items, list):
        return data

    clean_items: list[dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        url = item.get("url")

        if not _is_allowed_public_url(url):
            continue

        clean_items.append(item)

    result = dict(data)
    result["items"] = clean_items
    result["count"] = len(clean_items)

    return result


@mcp.tool(
    title="Search Swedish driving theory",
    description=(
        "Search public educational EngelskaKorkort.se Swedish driving-theory "
        "guides in English. Use for traffic rules, priority rules, road signs, "
        "road safety, Risk 1 and Risk 2, driving-test preparation, vehicle "
        "knowledge, environmental driving and Swedish driving-licence topics. "
        "Membership, account and checkout pages are excluded."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def search_theory(
    query: str,
    limit: int = 5,
) -> dict[str, Any]:
    """
    Search the public Swedish driving-theory knowledge base.
    """

    query = query.strip()

    if not query:
        return {
            "ok": False,
            "error": "query must not be empty",
        }

    if len(query) < 2:
        return {
            "ok": False,
            "error": "query must contain at least 2 characters",
        }

    if len(query) > 200:
        return {
            "ok": False,
            "error": "query must be 200 characters or fewer",
        }

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 5

    limit = max(1, min(limit, 10))

    data = _get_json(
        "search",
        {
            "q": query,
            "limit": limit,
        },
    )

    data = _filter_search_results(data)

    return _normalize_result(data)


@mcp.tool(
    title="Read a public theory guide",
    description=(
        "Read the full public text of one EngelskaKorkort.se Swedish "
        "driving-theory guide using the numeric content ID returned by "
        "search_theory. Membership, account and purchasing pages are excluded."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def get_theory_page(
    content_id: int,
) -> dict[str, Any]:
    """
    Get one public educational theory page by WordPress content ID.
    """

    try:
        content_id = int(content_id)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "error": "content_id must be an integer",
        }

    if content_id <= 0:
        return {
            "ok": False,
            "error": "content_id must be greater than zero",
        }

    data = _get_json(
        f"content/{content_id}"
    )

    if data.get("ok") is False:
        return data

    page_url = data.get("url")

    if not _is_allowed_public_url(page_url):
        return {
            "ok": False,
            "error": (
                "The requested page is outside the public educational "
                "scope of Sweden Driving Theory."
            ),
        }

    return _normalize_result(data)


@mcp.tool(
    title="Get the free theory test",
    description=(
        "Return the current public EngelskaKorkort.se free Swedish "
        "driving theory-test link in English."
    ),
    annotations=READ_ONLY_PUBLIC,
)
def get_free_theory_test() -> dict[str, Any]:
    """
    Return the public free English Swedish driving theory-test link.
    """

    data = _get_json("status")

    if data.get("ok") is False:
        return data

    links = (
        data.get("links", {})
        if isinstance(data, dict)
        else {}
    )

    if not isinstance(links, dict):
        links = {}

    free_test_url = links.get(
        "free_test",
        "https://engelskakorkort.se/free-theory-test/",
    )

    home_url = links.get(
        "home",
        "https://engelskakorkort.se/",
    )

    return {
        "ok": True,
        "provider": "EngelskaKorkort.se",
        "title": "Free Swedish Driving Theory Test in English",
        "url": free_test_url,
        "home": home_url,
    }


@mcp.custom_route(
    "/health",
    methods=["GET"],
)
async def health(_request):
    """
    Public health-check endpoint used by hosting and deployment checks.
    """

    return JSONResponse(
        {
            "status": "ok",
            "service": "Sweden Driving Theory MCP",
            "version": VERSION,
            "api_base": API_BASE,
            "tools": [
                "search_theory",
                "get_theory_page",
                "get_free_theory_test",
            ],
        }
    )


@mcp.custom_route(
    "/.well-known/openai-apps-challenge",
    methods=["GET"],
)
async def openai_apps_challenge(_request):
    """
    Serve the OpenAI domain-verification token exactly as provided
    through the OPENAI_APPS_CHALLENGE environment variable.
    """

    token = os.getenv(
        "OPENAI_APPS_CHALLENGE",
        "",
    ).strip()

    if not token:
        return PlainTextResponse(
            "Not configured",
            status_code=404,
        )

    return PlainTextResponse(
        token,
        media_type="text/plain",
    )


def _transport_security() -> TransportSecuritySettings:
    """
    Configure MCP transport security.

    MCP_ALLOWED_HOSTS should contain the production Render hostname.
    MCP_ALLOWED_ORIGINS is optional.
    """

    raw_hosts = os.getenv(
        "MCP_ALLOWED_HOSTS",
        "",
    ).strip()

    raw_origins = os.getenv(
        "MCP_ALLOWED_ORIGINS",
        "",
    ).strip()

    if raw_hosts:
        hosts = [
            host.strip()
            for host in raw_hosts.split(",")
            if host.strip()
        ]

        origins = [
            origin.strip()
            for origin in raw_origins.split(",")
            if origin.strip()
        ]

        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts,
            allowed_origins=origins,
        )

    # Render and similar managed reverse proxies control the Host header.
    # For production/public review, MCP_ALLOWED_HOSTS should be configured.
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )


if __name__ == "__main__":
    port = int(
        os.getenv(
            "PORT",
            "8000",
        )
    )

    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=_transport_security(),
    )
