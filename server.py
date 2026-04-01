#!/usr/bin/env python3
"""
Snowforge MCP — ServiceNow instance connector for SNODGE.
Chrome CDP auth, instance inspection, script execution, and verification.

Snowforge is the eyes and hands. SNODGE (Claude Project) is the brain.
- Snowforge connects to the instance and gathers real data (groups, users, schemas)
- SNODGE generates scripts using that real data
- Snowforge executes the scripts and verifies results

Credits:
- Patrick Spieler — SNODGE concept (automated modular demo data generation)
- Adrian Mahn — original MCP server code

Usage: uv run --with mcp --with websockets python3 server.py
"""

import json
import sys
import os
import subprocess
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Any

# ── Chrome CDP Auth ──────────────────────────────────────────────────────────

CDP_PORT = 9223  # Separate from Alfred's 9222
CHROME_PROFILE = os.path.expanduser("~/.snowforge-profile")

_instance_url: str | None = None
_session_cookies: str | None = None


def _cdp_get(path: str) -> Any:
    """GET request to Chrome DevTools Protocol HTTP API."""
    req = urllib.request.Request(f"http://localhost:{CDP_PORT}{path}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())


def _cdp_ws_command(ws_url: str, method: str, params: dict | None = None) -> Any:
    """Send a CDP command over WebSocket and return the result."""
    import websockets.sync.client as ws_client

    with ws_client.connect(ws_url) as ws:
        msg_id = 1
        cmd = {"id": msg_id, "method": method}
        if params:
            cmd["params"] = params
        ws.send(json.dumps(cmd))

        while True:
            resp = json.loads(ws.recv(timeout=10))
            if resp.get("id") == msg_id:
                return resp.get("result", {})


def launch_chrome(instance_url: str) -> str:
    """Launch Chrome with remote debugging to the given SN instance."""
    global _instance_url, _session_cookies
    _instance_url = instance_url.rstrip("/")
    _session_cookies = None

    try:
        _cdp_get("/json/version")
        return "Chrome already running — extracting cookies..."
    except Exception:
        pass

    os.makedirs(CHROME_PROFILE, exist_ok=True)
    chrome_paths = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "google-chrome",
        "chromium",
    ]
    chrome_bin = None
    for p in chrome_paths:
        if os.path.exists(p):
            chrome_bin = p
            break
    if not chrome_bin:
        try:
            chrome_bin = subprocess.check_output(["which", "google-chrome"], text=True, timeout=3).strip()
        except Exception:
            pass
    if not chrome_bin:
        chrome_bin = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

    subprocess.Popen(
        [
            chrome_bin,
            f"--remote-debugging-port={CDP_PORT}",
            f"--user-data-dir={CHROME_PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--disable-sync",
            _instance_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    for _ in range(30):
        try:
            _cdp_get("/json/version")
            return f"Chrome launched — navigate to {_instance_url} and log in."
        except Exception:
            time.sleep(0.5)

    raise RuntimeError("Chrome did not start within 15 seconds")


def extract_cookies(instance_url: str | None = None) -> str:
    """Extract session cookies from Chrome for the SN instance."""
    global _session_cookies, _instance_url

    if instance_url:
        _instance_url = instance_url.rstrip("/")

    if not _instance_url:
        raise RuntimeError("No instance URL set — call connect_instance first")

    version = _cdp_get("/json/version")
    ws_url = version["webSocketDebuggerUrl"]

    from urllib.parse import urlparse
    domain = urlparse(_instance_url).hostname

    result = _cdp_ws_command(ws_url, "Storage.getCookies", {"browserContextId": None})
    if not result.get("cookies"):
        result = _cdp_ws_command(ws_url, "Network.getAllCookies")

    cookies = result.get("cookies", [])
    sn_cookies = [c for c in cookies if domain and (c.get("domain", "").endswith(domain) or domain.endswith(c.get("domain", "").lstrip(".")))]

    if not sn_cookies:
        raise RuntimeError(
            f"No cookies found for {domain}. Make sure you're logged into ServiceNow in the Chrome window."
        )

    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in sn_cookies)
    _session_cookies = cookie_str

    sys.stderr.write(f"[snowforge] Extracted {len(sn_cookies)} cookies for {domain}\n")
    return cookie_str


# ── ServiceNow API ───────────────────────────────────────────────────────────

def _sn_request(method: str, path: str, body: dict | None = None) -> dict:
    """Make an authenticated request to the ServiceNow REST API."""
    if not _instance_url:
        raise RuntimeError("Not connected — call connect_instance first")
    if not _session_cookies:
        raise RuntimeError("No session cookies — call connect_instance and log in first")

    url = f"{_instance_url}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Cookie", _session_cookies)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("X-UserToken", "")  # CSRF prevention

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            if not raw:
                return {"status": "ok"}
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        if e.code == 401:
            raise RuntimeError(
                "Session expired (401). Ask the user to log in again in Chrome, then call connect_instance."
            )
        return {"error": error_body[:500], "status": e.code}


def _validate_table(table: str) -> str:
    """Validate table name to prevent path traversal."""
    import re
    if not re.match(r"^[a-z_][a-z0-9_]*$", table, re.IGNORECASE):
        raise ValueError(f"Invalid table name: {table!r}")
    return table


def _validate_sys_id(sys_id: str) -> str:
    """Validate sys_id format (32-char hex)."""
    import re
    if not re.match(r"^[0-9a-f]{32}$", sys_id, re.IGNORECASE):
        raise ValueError(f"Invalid sys_id: {sys_id!r} — expected 32-character hex string")
    return sys_id


# ── MCP Server ───────────────────────────────────────────────────────────────

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "snowforge",
    instructions="""Snowforge — ServiceNow instance connector for SNODGE demo data generation.

ROLE: Snowforge is the eyes and hands. SNODGE (Claude Project) is the brain.
- Snowforge connects, inspects, executes, and verifies
- SNODGE decides what data to create and generates the scripts

WORKFLOW:
1. connect_instance → Chrome launches, user logs in (SSO/MFA/whatever)
2. complete_login → session cookies extracted
3. INSPECT the instance for SNODGE:
   - describe_table → check what fields exist, which are mandatory
   - list_records → find real sys_ids (groups, users, rel types, categories)
   - check_table_exists → verify plugins are active before generating scripts
4. SNODGE generates Background Scripts using the real data from step 3
5. run_script → execute SNODGE scripts on the instance
6. list_records → verify records were created correctly""",
)


# ── Tools: Connection ────────────────────────────────────────────────────────

@mcp.tool()
def connect_instance(instance_name: str) -> str:
    """Connect to a ServiceNow instance. Launches Chrome for login.

    Args:
        instance_name: Instance name (e.g. 'acmedemo') or full URL (e.g. 'https://acmedemo.service-now.com')
    """
    if instance_name.startswith("http"):
        url = instance_name.rstrip("/")
    else:
        url = f"https://{instance_name}.service-now.com"

    result = launch_chrome(url)

    try:
        extract_cookies(url)
        return f"Connected to {url} — session cookies extracted. Ready to query."
    except Exception:
        return f"{result}\n\nPlease log in to ServiceNow in the Chrome window, then say 'ready' and I'll extract the session."


@mcp.tool()
def complete_login() -> str:
    """Extract session cookies after the user has logged in via Chrome.
    Call this after the user confirms they've logged in."""
    cookies = extract_cookies()
    return f"Session authenticated — {len(cookies.split(';'))} cookies extracted. Ready to query."


# ── Tools: Instance Inspection (feed data to SNODGE) ────────────────────────

@mcp.tool()
def describe_table(table: str) -> str:
    """Get the schema/field definitions for a ServiceNow table.
    Returns field names, types, labels, whether they're mandatory, and reference targets.

    Use this BEFORE generating scripts to understand what fields exist on this specific instance.

    Args:
        table: Table name (e.g. incident, cmdb_ci_server, sn_customerservice_case)
    """
    table = _validate_table(table)

    dict_result = _sn_request(
        "GET",
        f"/api/now/table/sys_dictionary?sysparm_query=name={table}&sysparm_fields=element,column_label,internal_type,mandatory,reference&sysparm_limit=200",
    )

    if "error" in dict_result:
        return f"Could not describe table: {dict_result['error']}"

    fields = dict_result.get("result", [])
    if not fields:
        return f"No field definitions found for table '{table}'. Check the table name or verify the plugin is active."

    lines = [f"Table: {table} — {len(fields)} fields\n"]
    lines.append(f"{'Field':<30} {'Label':<30} {'Type':<20} {'Req':<5} {'Reference'}")
    lines.append("-" * 120)

    for f in sorted(fields, key=lambda x: x.get("element", "")):
        element = f.get("element", "")
        if not element or element.startswith("sys_"):
            continue
        label = f.get("column_label", "")
        ftype = f.get("internal_type", {})
        if isinstance(ftype, dict):
            ftype = ftype.get("value", ftype.get("display_value", ""))
        mandatory = "YES" if f.get("mandatory") == "true" else ""
        ref = f.get("reference", {})
        if isinstance(ref, dict):
            ref = ref.get("value", ref.get("display_value", ""))
        lines.append(f"{element:<30} {label:<30} {ftype:<20} {mandatory:<5} {ref}")

    return "\n".join(lines)


@mcp.tool()
def list_records(
    table: str,
    query: str = "",
    fields: str = "",
    limit: int = 20,
    offset: int = 0,
    order_by: str = "",
) -> str:
    """Query records from any ServiceNow table via REST API.

    Primary use: gather real sys_ids for SNODGE scripts (groups, users, rel types, categories).
    Secondary use: verify records after script execution.

    Args:
        table: Table name (e.g. sys_user_group, cmdb_rel_type, sys_user)
        query: Encoded query filter (e.g. 'active=true^nameSTARTSWITHIT')
        fields: Comma-separated fields to return (e.g. 'sys_id,name' — empty = all)
        limit: Max records to return (default 20, max 100)
        offset: Pagination offset
        order_by: Field to order by (prefix with - for descending)
    """
    table = _validate_table(table)
    limit = min(limit, 100)

    params = f"sysparm_limit={limit}&sysparm_offset={offset}"
    if query:
        q = query
        if order_by:
            q += f"^ORDERBY{order_by}"
        params += f"&sysparm_query={urllib.parse.quote(q)}"
    elif order_by:
        params += f"&sysparm_query={urllib.parse.quote(f'ORDERBY{order_by}')}"
    if fields:
        params += f"&sysparm_fields={fields}"

    result = _sn_request("GET", f"/api/now/table/{table}?{params}")

    if "error" in result:
        return f"Error: {result['error']}"

    records = result.get("result", [])
    return json.dumps({"count": len(records), "records": records}, indent=2)


@mcp.tool()
def get_record(table: str, sys_id: str, fields: str = "") -> str:
    """Get a single record by sys_id.

    Args:
        table: Table name
        sys_id: Record sys_id (32-char hex)
        fields: Comma-separated fields to return (empty = all)
    """
    table = _validate_table(table)
    sys_id = _validate_sys_id(sys_id)

    params = f"?sysparm_fields={fields}" if fields else ""
    result = _sn_request("GET", f"/api/now/table/{table}/{sys_id}{params}")

    if "error" in result:
        return f"Error: {result['error']}"

    return json.dumps(result.get("result", result), indent=2)


@mcp.tool()
def check_table_exists(table: str) -> str:
    """Check if a table exists on the instance (i.e. if the required plugin is active).

    Use this to verify module availability before SNODGE generates scripts.
    E.g. check sn_customerservice_case before generating CSM scripts.

    Args:
        table: Table name to check
    """
    table = _validate_table(table)

    result = _sn_request("GET", f"/api/now/table/{table}?sysparm_limit=0")

    if "error" in result:
        status_code = result.get("status", "unknown")
        if status_code == 404 or "Invalid table" in str(result.get("error", "")):
            return f"Table '{table}' does NOT exist. The required plugin may not be activated."
        return f"Error checking table: {result['error']}"

    return f"Table '{table}' exists and is accessible."


# ── Tools: Script Execution ──────────────────────────────────────────────────

@mcp.tool()
def run_script(script: str) -> str:
    """Execute a Background Script on the ServiceNow instance (server-side JavaScript).

    This is the primary tool for running SNODGE-generated scripts.
    Scripts run in ServiceNow's Rhino engine (ES5 only).

    IMPORTANT: Always show the script to the user and get approval before running.

    Args:
        script: JavaScript code to execute (GlideRecord API, ES5 syntax only)
    """
    if not _instance_url or not _session_cookies:
        raise RuntimeError("Not connected — call connect_instance first")

    result = _sn_request(
        "POST",
        "/api/now/table/sys_script_fix",
        {
            "name": f"Snowforge Script {int(time.time())}",
            "script": script,
            "run_type": "once",
        },
    )

    if "error" in result:
        return f"Script execution failed: {result['error']}"

    return f"Script submitted.\n\n{json.dumps(result.get('result', {}), indent=2)}"


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
