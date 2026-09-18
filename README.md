# Sweden Driving Theory MCP

Read-only MCP server for EngelskaKorkort.se.

## Tools

- `search_theory`
- `get_theory_page`
- `get_membership_plans`
- `get_free_theory_test`

## Local run

```bash
pip install -r requirements.txt
python server.py
```

MCP endpoint: `http://localhost:8000/mcp`
Health endpoint: `http://localhost:8000/health`

## Render

Build command:

```text
pip install -r requirements.txt
```

Start command:

```text
python server.py
```

The server reads Render's `PORT` variable automatically.

Optional environment variables:

- `ENGELSKAKORKORT_API_BASE=https://engelskakorkort.se/wp-json/ek-chatgpt/v1`
- `MCP_ALLOWED_HOSTS=your-service.onrender.com,your-service.onrender.com:*`

For production with a custom domain, set `MCP_ALLOWED_HOSTS` to the final MCP hostname, for example:

```text
mcp.engelskakorkort.se,mcp.engelskakorkort.se:*
```
