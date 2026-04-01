#!/usr/bin/env python3
"""
Snowforge MCP — ServiceNow demo data forge.
Chrome CDP auth, full CRUD on any table, prefix-based cleanup.

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

    # Check if Chrome is already running on our port
    try:
        _cdp_get("/json/version")
        return "Chrome already running — extracting cookies..."
    except Exception:
        pass

    # Launch Chrome
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
    instructions="""Snowforge — ServiceNow demo data forge. Connects to any instance via Chrome session (SSO/MFA compatible).

WORKFLOW:
1. User provides instance name → call connect_instance (launches Chrome)
2. User logs in via Chrome (SSO/MFA/whatever their instance uses)
3. User says "ready" → call complete_login (extracts session cookies)
4. Generate data using create_record / create_records_batch / run_script
5. Clean up with cleanup_by_prefix when done

═══════════════════════════════════════════════════════════════════
 DEMO DATA GENERATION — DOMAIN KNOWLEDGE
═══════════════════════════════════════════════════════════════════

When generating demo data, follow this creation order strictly.
Parent records MUST exist before children that reference them.

── CSDM FOUNDATION (always create first) ──────────────────────

Creation order:
1. cmdb_ci_business_capability — Business Capabilities (top of hierarchy)
2. cmdb_ci_service_auto → Business Services (references business_capability)
3. cmdb_ci_service_technical → Technical Services (references business_service)
4. cmdb_ci_service → Application Services (references technical_service)
5. cmdb_ci_server / cmdb_ci_db_instance / cmdb_ci_lb — CIs (reference app service)
6. cmdb_rel_ci — Relationships between CIs (type + parent + child sys_ids)

Key fields for services:
- name: Always prefix with the project prefix (e.g. "SF-Acme-Payment Gateway")
- service_classification: "Business Service" / "Technical Service" / "Application Service"
- operational_status: 1 (Operational)
- busines_criticality: "1 - most critical" / "2 - somewhat critical" / "3 - less critical"

Relationship types (cmdb_rel_type):
- "Depends on::Used by" — service dependencies
- "Runs on::Runs" — app-to-server
- "Contains::Contained by" — logical grouping

IMPORTANT: After creating CSDM records, verify service maps render by checking
cmdb_rel_ci relationships. Missing or wrong relationship types = broken maps.

── ITSM OVERLAY ────────────────────────────────────────────────

Tables: incident, problem, change_request, known_error
Creation order: problem → known_error → incident → change_request

Realistic ratios (per ~20 record set):
- 8-10 incidents (mix of P1-P4, mostly P3)
- 3-4 problems (root cause investigations)
- 2-3 known errors (documented workarounds)
- 3-4 change requests (mix: standard, normal, emergency)

Story patterns (make data tell a story):
- "Change caused incident": change_request → incident referencing the change
- "Problem identified": multiple incidents → problem links them
- "Known error with workaround": problem → known_error with workaround field

Key fields:
- incident: short_description, description, priority, urgency, impact, category, subcategory, assignment_group, cmdb_ci, state
- problem: short_description, priority, known_error (boolean), related_incidents
- change_request: short_description, type (standard/normal/emergency), risk, impact, start_date, end_date, cmdb_ci
- Use describe_table to discover instance-specific fields

GOTCHAS:
- assignment_group must be a valid sys_id — use list_records on sys_user_group first
- category/subcategory must match — invalid combos get silently corrected by business rules
- state transitions: you can only set certain states at creation; others require intermediate states
- Always set caller_id on incidents (use list_records on sys_user to find valid users)

── CSM OVERLAY ─────────────────────────────────────────────────

Tables: customer_account, customer_contact, sn_customerservice_case
Creation order: customer_account → customer_contact → case

Key fields:
- customer_account: name, account_number, industry, city, state, country
- customer_contact: first_name, last_name, email, phone, account (references customer_account)
- sn_customerservice_case: short_description, account, contact, priority, product, category

GOTCHAS:
- Entitlements (service_entitlement): if the instance has entitlement checking enabled,
  cases without valid entitlements may get auto-rejected by business rules
- SLA definitions: attach to cases for realistic SLA tracking demo scenarios

── HRSD OVERLAY ────────────────────────────────────────────────

Tables: sn_hr_core_case, sn_hr_le_lifecycle_event, sn_hr_le_activity
Creation order: lifecycle_event_type → lifecycle_event → activities → HR cases

Key fields:
- sn_hr_core_case: short_description, hr_service, subject_person, opened_for, state
- sn_hr_le_lifecycle_event: name, lifecycle_event_type, employee
- sn_hr_le_activity: name, lifecycle_event, assignment_group, state, order

GOTCHAS:
- hr_service must reference a valid HR service from sn_hr_core_service
- subject_person and opened_for must be valid sys_user sys_ids
- lifecycle_event_type controls which activities auto-generate — check the type first
- Some HR tables require the HR plugin to be activated

═══════════════════════════════════════════════════════════════════
 PREFIX CONVENTION
═══════════════════════════════════════════════════════════════════

ALL generated records MUST use a prefix in their name/short_description:
  Format: SF-{CompanyShortName}-{description}
  Example: SF-Acme-Payment Gateway Service

This enables cleanup_by_prefix to find and delete all generated data.
The prefix must appear in the first field that makes sense:
- Services/CIs: name field
- Incidents/problems/changes/cases: short_description field
- Contacts: last_name field (e.g. "SF-Acme-Smith")
- Accounts: name field

═══════════════════════════════════════════════════════════════════
 BEST PRACTICES
═══════════════════════════════════════════════════════════════════

1. ALWAYS describe_table before creating records in an unfamiliar table
2. ALWAYS list_records on reference tables to get valid sys_ids (don't guess)
3. Create in dependency order: CSDM → ITSM → CSM → HRSD
4. Use create_records_batch for efficiency (up to 50 per call)
5. Verify after creation: list_records with prefix query to confirm
6. If a create fails, check the error — often it's a missing required field or bad reference

CROSS-REFERENCE: Use SSC_Retrieval to understand ServiceNow module best practices and data model relationships. Use account_insights to check customer data patterns.""",
)


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
    """Extract session cookies after the user has logged in via Chrome. Call this after the user confirms they've logged in."""
    cookies = extract_cookies()
    return f"Session authenticated — {len(cookies.split(';'))} cookies extracted. Ready to query."


@mcp.tool()
def list_records(
    table: str,
    query: str = "",
    fields: str = "",
    limit: int = 20,
    offset: int = 0,
    order_by: str = "",
) -> str:
    """List records from any ServiceNow table.

    Args:
        table: Table name (e.g. incident, sn_grc_profile, cmdb_ci_server)
        query: Encoded query filter (e.g. 'active=true^priority=1')
        fields: Comma-separated fields to return (empty = all fields)
        limit: Max records to return (default 20, max 100)
        offset: Pagination offset
        order_by: Field to order by (prefix with - for descending, e.g. '-sys_created_on')
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
def create_record(table: str, record: dict) -> str:
    """Create a new record in any ServiceNow table.

    IMPORTANT: Before creating, use describe_table to understand required fields and valid values.
    For reference fields, use list_records to find valid sys_ids.
    Always prefix record names with SF-{CompanyName}- for cleanup.

    Args:
        table: Table name (e.g. incident, sn_grc_profile)
        record: Field/value pairs for the new record
    """
    table = _validate_table(table)

    result = _sn_request("POST", f"/api/now/table/{table}", record)

    if "error" in result:
        return f"Error creating record: {result['error']}"

    created = result.get("result", {})
    sys_id = created.get("sys_id", "unknown")
    number = created.get("number", "")
    label = f" ({number})" if number else ""
    return f"Created {table} record{label}: sys_id={sys_id}\n\n{json.dumps(created, indent=2)}"


@mcp.tool()
def create_records_batch(table: str, records: list[dict]) -> str:
    """Create multiple records in a ServiceNow table. Records are created sequentially.

    IMPORTANT: Maximum 50 records per call to prevent runaway creation.
    Always prefix record names with SF-{CompanyName}- for cleanup.

    Args:
        table: Table name
        records: List of field/value dicts (max 50)
    """
    table = _validate_table(table)

    if len(records) > 50:
        return "Maximum 50 records per batch. Split into smaller batches."

    results = []
    for i, rec in enumerate(records):
        result = _sn_request("POST", f"/api/now/table/{table}", rec)
        if "error" in result:
            results.append(f"[FAIL] Record {i+1}: {result['error'][:200]}")
        else:
            created = result.get("result", {})
            sys_id = created.get("sys_id", "?")
            number = created.get("number", "")
            label = f" ({number})" if number else ""
            results.append(f"[OK] Record {i+1}{label}: {sys_id}")

    return f"Batch create on {table}: {len(records)} records\n\n" + "\n".join(results)


@mcp.tool()
def update_record(table: str, sys_id: str, record: dict) -> str:
    """Update an existing record.

    Args:
        table: Table name
        sys_id: Record sys_id (32-char hex)
        record: Field/value pairs to update (only include fields you want to change)
    """
    table = _validate_table(table)
    sys_id = _validate_sys_id(sys_id)

    result = _sn_request("PATCH", f"/api/now/table/{table}/{sys_id}", record)

    if "error" in result:
        return f"Error: {result['error']}"

    updated = result.get("result", {})
    return f"Updated {table}/{sys_id}\n\n{json.dumps(updated, indent=2)}"


@mcp.tool()
def delete_record(table: str, sys_id: str) -> str:
    """Delete a record. IMPORTANT: Always confirm with the user before deleting.

    Args:
        table: Table name
        sys_id: Record sys_id (32-char hex)
    """
    table = _validate_table(table)
    sys_id = _validate_sys_id(sys_id)

    result = _sn_request("DELETE", f"/api/now/table/{table}/{sys_id}")

    if "error" in result:
        return f"Error: {result['error']}"

    return f"Deleted {table}/{sys_id}"


@mcp.tool()
def describe_table(table: str) -> str:
    """Get the schema/field definitions for a ServiceNow table.
    Returns field names, types, labels, and whether they're mandatory.
    Essential before creating records — shows what fields are available and required.

    Args:
        table: Table name (e.g. incident, cmdb_ci_server)
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
        return f"No field definitions found for table '{table}'. Check the table name."

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
def cleanup_by_prefix(prefix: str, tables: list[str] | None = None) -> str:
    """Delete all Snowforge-generated records matching a prefix.

    Searches common tables (or specified tables) for records where name or
    short_description starts with the given prefix, then deletes them in
    reverse dependency order (children first, parents last).

    Args:
        prefix: The prefix to search for (e.g. 'SF-Acme')
        tables: Optional list of tables to clean. If not provided, cleans all standard tables.
    """
    # Default tables in reverse dependency order (children first)
    default_tables = [
        # HRSD
        ("sn_hr_le_activity", "short_description"),
        ("sn_hr_le_lifecycle_event", "name"),
        ("sn_hr_core_case", "short_description"),
        # CSM
        ("sn_customerservice_case", "short_description"),
        ("customer_contact", "last_name"),
        ("customer_account", "name"),
        # ITSM
        ("change_request", "short_description"),
        ("known_error", "short_description"),
        ("incident", "short_description"),
        ("problem", "short_description"),
        # CSDM — CIs first, then services, then capabilities
        ("cmdb_rel_ci", None),  # Special: handled via parent/child lookup
        ("cmdb_ci_server", "name"),
        ("cmdb_ci_db_instance", "name"),
        ("cmdb_ci_lb", "name"),
        ("cmdb_ci_service", "name"),
        ("cmdb_ci_service_technical", "name"),
        ("cmdb_ci_service_auto", "name"),
        ("cmdb_ci_business_capability", "name"),
    ]

    if tables:
        # User specified tables — assume name field, they can use short_description in query
        target_tables = [(t, "name") for t in tables]
    else:
        target_tables = default_tables

    results = []
    total_deleted = 0

    for table, field in target_tables:
        try:
            table = _validate_table(table)
        except ValueError:
            results.append(f"[SKIP] {table}: invalid table name")
            continue

        # Build query
        if field is None:
            # cmdb_rel_ci: skip for now, relationships get orphaned but harmless
            continue
        query = f"{field}STARTSWITH{prefix}"

        # Find matching records
        try:
            find_result = _sn_request(
                "GET",
                f"/api/now/table/{table}?sysparm_query={urllib.parse.quote(query)}&sysparm_fields=sys_id,{field}&sysparm_limit=200",
            )
        except RuntimeError as e:
            results.append(f"[SKIP] {table}: {e}")
            continue

        if "error" in find_result:
            # Table might not exist on this instance — skip silently
            continue

        records = find_result.get("result", [])
        if not records:
            continue

        # Delete each record
        deleted = 0
        failed = 0
        for rec in records:
            sid = rec.get("sys_id")
            if not sid:
                continue
            try:
                del_result = _sn_request("DELETE", f"/api/now/table/{table}/{sid}")
                if "error" in del_result:
                    failed += 1
                else:
                    deleted += 1
            except Exception:
                failed += 1

        total_deleted += deleted
        status = f"deleted {deleted}"
        if failed:
            status += f", {failed} failed"
        results.append(f"[{table}] {status}")

    summary = f"Cleanup complete: {total_deleted} records deleted across {len(results)} tables"
    if results:
        summary += "\n\n" + "\n".join(results)
    else:
        summary += f"\n\nNo records found with prefix '{prefix}'"

    return summary


@mcp.tool()
def run_script(script: str) -> str:
    """Execute a background script on the ServiceNow instance (server-side JavaScript).

    IMPORTANT: Always show the script to the user and get approval before running.
    Uses the sys_script_fix table to submit one-time fix scripts.

    Args:
        script: JavaScript code to execute (ServiceNow server-side GlideRecord API)
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
