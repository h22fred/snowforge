# Snowforge MCP

The hands and eyes for [SNODGE](https://en.wikipedia.org/wiki/SNODGE) — connects Claude to any ServiceNow instance via Chrome (SSO/MFA compatible) so SNODGE can inspect, execute, and verify demo data scripts.

## Credits

This project stands on the shoulders of two people:

- **Patrick Spieler** — creator of the SNODGE concept: the idea that demo data generation for ServiceNow should be automated, modular, and SC-friendly. The CSDM-first approach, the 4-script architecture, the prefix-based cleanup — all Patrick's design.
- **Adrian Mahn** — original MCP server code. Adrian built the first working ServiceNow MCP server that proved Claude could talk directly to a ServiceNow instance. This project extends his foundation with Chrome-based auth.

---

## How Snowforge + SNODGE work together

**SNODGE** (Claude Project) is the brain — it knows what data to create, in what order, with what gotchas. It generates Background Scripts using GlideRecord + `setWorkflow(false)`.

**Snowforge** (this MCP server) is the hands — it connects to the instance, gathers real data, executes scripts, and verifies results.

```
┌─────────────────────────────────────────────────────┐
│  Claude Desktop (with SNODGE Project)               │
│                                                     │
│  1. User: "Generate ITSM data for Acme Healthcare"  │
│                                                     │
│  2. Snowforge: inspect instance                     │
│     ├── describe_table → field schemas              │
│     ├── list_records  → real group/user sys_ids     │
│     └── check_table_exists → plugin verification    │
│                                                     │
│  3. SNODGE: generate scripts using real data        │
│     └── ES5, setWorkflow(false), prefix-based       │
│                                                     │
│  4. Snowforge: execute + verify                     │
│     ├── run_script → submit to Background Scripts   │
│     └── list_records → confirm records created      │
└─────────────────────────────────────────────────────┘
```

## Setup

### Prerequisites
- macOS or Linux
- [Claude Desktop](https://claude.ai/download)
- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Google Chrome

### Install

```bash
# Clone the repo
git clone https://github.com/h22fred/snowforge.git
cd snowforge

# Copy server to a location outside ~/Documents (macOS sandbox workaround)
mkdir -p ~/.snowforge
cp server.py ~/.snowforge/server.py
```

### Add to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "snowforge": {
      "command": "/opt/homebrew/bin/uv",
      "args": ["run", "--with", "mcp", "--with", "websockets", "python3", "/Users/YOUR_USERNAME/.snowforge/server.py"]
    }
  }
}
```

> **Note:** Use the full path to `uv` (run `which uv` to find it). Claude Desktop doesn't load your shell profile, so bare `uv` won't be found.

> **Note:** On macOS, Claude Desktop's python subprocess can't read files in `~/Documents` due to sandboxing. That's why we copy to `~/.snowforge/`.

Restart Claude Desktop. Snowforge should appear as a connected Local MCP server.

### Add the SNODGE Project

Snowforge is just the tooling — the domain knowledge lives in a separate Claude Project called **NOW Data Gen** (SNODGE). Add Snowforge to that project so Claude has both the brains and the hands.

## Usage

1. **Connect**: "Connect to acmedemo" — Chrome opens to your instance
2. **Log in**: SSO/MFA/whatever your instance uses
3. **Say "ready"**: Claude extracts session cookies
4. **Inspect**: Claude uses Snowforge to gather groups, users, schemas from the live instance
5. **Generate**: SNODGE generates Background Scripts using real sys_ids
6. **Execute**: Snowforge runs the scripts via `run_script`
7. **Verify**: Snowforge queries the instance to confirm records exist

## Tools

| Tool | Purpose |
|------|---------|
| `connect_instance` | Launch Chrome to an SN instance for login |
| `complete_login` | Extract session cookies after login |
| `describe_table` | Get table schema (fields, types, mandatory, references) |
| `list_records` | Query any table — find groups, users, rel types, categories |
| `get_record` | Get a single record by sys_id |
| `check_table_exists` | Verify a plugin/table is active before generating scripts |
| `validate_script` | Sanity-check a script before execution (ES5 compliance, PREFIX, setWorkflow, hardcoded sys_ids) |
| `run_script` | Execute a Background Script (server-side JS, ES5) |

## Why not just use the REST API for everything?

SNODGE generates GlideRecord scripts with `setWorkflow(false)`, which **bypasses business rules**. This is critical for demo data:

- No state transition restrictions (set any incident state directly)
- No entitlement checks rejecting CSM cases
- No auto-generated activities overriding your data
- No cross-scope delete restrictions on K8s/cloud tables

The REST API hits every business rule, making bulk data generation fragile. GlideRecord scripts via Background Scripts are the right tool for the job. Snowforge's role is to make those scripts smarter (real sys_ids) and easier to run (no copy-paste).

## License

MIT
