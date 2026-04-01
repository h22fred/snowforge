#!/usr/bin/env python3
"""
Custom ServiceNow MCP Server
Full CRUD for any ServiceNow table, including GRC.
Usage: python3 servicenow_mcp_server.py
"""

import json
import sys
import os
import urllib.request
import urllib.error
import base64
from typing import Any

# ── Configuration ────────────────────────────────────────────────────────────
INSTANCE_URL = os.environ.get("SN_INSTANCE_URL", "https://amutahdemo.service-now.com")
USERNAME     = os.environ.get("SN_USERNAME", "admin")
PASSWORD     = os.environ.get("SN_PASSWORD", "")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_header() -> str:
    token = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    return f"Basic {token}"

def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{INSTANCE_URL}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", _auth_header())
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode(), "status": e.code}

def sn_list(table: str, query: str = "", fields: str = "", limit: int = 20, offset: int = 0) -> dict:
    params = f"sysparm_limit={limit}&sysparm_offset={offset}"
    if query:  params += f"&sysparm_query={urllib.parse.quote(query)}"
    if fields: params += f"&sysparm_fields={fields}"
    return _request("GET", f"/api/now/table/{table}?{params}")

def sn_get(table: str, sys_id: str, fields: str = "") -> dict:
    params = f"?sysparm_fields={fields}" if fields else ""
    return _request("GET", f"/api/now/table/{table}/{sys_id}{params}")

def sn_create(table: str, record: dict) -> dict:
    return _request("POST", f"/api/now/table/{table}", record)

def sn_update(table: str, sys_id: str, record: dict) -> dict:
    return _request("PATCH", f"/api/now/table/{table}/{sys_id}", record)

def sn_delete(table: str, sys_id: str) -> dict:
    return _request("DELETE", f"/api/now/table/{table}/{sys_id}")

# ── MCP Protocol ──────────────────────────────────────────────────────────────

import urllib.parse

TOOLS = [
    {
        "name": "list_records",
        "description": "List records from any ServiceNow table with optional filtering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table":  {"type": "string", "description": "Table name, e.g. sn_grc_profile, sn_policy_control, incident"},
                "query":  {"type": "string", "description": "Encoded query, e.g. active=true^state=1"},
                "fields": {"type": "string", "description": "Comma-separated fields to return"},
                "limit":  {"type": "integer", "description": "Max records (default 20)"},
                "offset": {"type": "integer", "description": "Pagination offset"}
            },
            "required": ["table"]
        }
    },
    {
        "name": "get_record",
        "description": "Get a single ServiceNow record by sys_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table":  {"type": "string", "description": "Table name"},
                "sys_id": {"type": "string", "description": "Record sys_id"},
                "fields": {"type": "string", "description": "Comma-separated fields to return"}
            },
            "required": ["table", "sys_id"]
        }
    },
    {
        "name": "create_record",
        "description": "Create a new record in any ServiceNow table.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table":  {"type": "string", "description": "Table name, e.g. sn_grc_profile"},
                "record": {"type": "object", "description": "Field/value pairs for the new record"}
            },
            "required": ["table", "record"]
        }
    },
    {
        "name": "update_record",
        "description": "Update an existing ServiceNow record by sys_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table":  {"type": "string", "description": "Table name"},
                "sys_id": {"type": "string", "description": "Record sys_id"},
                "record": {"type": "object", "description": "Field/value pairs to update"}
            },
            "required": ["table", "sys_id", "record"]
        }
    },
    {
        "name": "delete_record",
        "description": "Delete a ServiceNow record by sys_id. Use with caution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "table":  {"type": "string", "description": "Table name"},
                "sys_id": {"type": "string", "description": "Record sys_id"}
            },
            "required": ["table", "sys_id"]
        }
    }
]

def handle_tool(name: str, args: dict) -> Any:
    if name == "list_records":
        return sn_list(
            args["table"],
            args.get("query", ""),
            args.get("fields", ""),
            args.get("limit", 20),
            args.get("offset", 0)
        )
    elif name == "get_record":
        return sn_get(args["table"], args["sys_id"], args.get("fields", ""))
    elif name == "create_record":
        return sn_create(args["table"], args["record"])
    elif name == "update_record":
        return sn_update(args["table"], args["sys_id"], args["record"])
    elif name == "delete_record":
        return sn_delete(args["table"], args["sys_id"])
    else:
        return {"error": f"Unknown tool: {name}"}

def send(obj: dict):
    line = json.dumps(obj)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "servicenow-grc-mcp", "version": "1.0.0"}
            }})

        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})

        elif method == "tools/call":
            tool_name = msg["params"]["name"]
            tool_args  = msg["params"].get("arguments", {})
            result = handle_tool(tool_name, tool_args)
            send({"jsonrpc": "2.0", "id": msg_id, "result": {
                "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
            }})

        elif method == "notifications/initialized":
            pass  # no response needed

        else:
            if msg_id is not None:
                send({"jsonrpc": "2.0", "id": msg_id, "error": {
                    "code": -32601, "message": f"Method not found: {method}"
                }})

if __name__ == "__main__":
    main()
