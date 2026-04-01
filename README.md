# Snowforge MCP

A ServiceNow MCP server for Claude Desktop — connect to any instance via Chrome (SSO/MFA compatible), generate production-quality demo data, and manage any table. Built for Solution Consultants who need realistic, interconnected data in minutes, not days.

## Credits

This project stands on the shoulders of two people:

- **Patrick Spieler** — creator of the SNODGE concept: the idea that demo data generation for ServiceNow should be automated, modular, and SC-friendly. The CSDM-first approach, the 4-script architecture, the prefix-based cleanup — all Patrick's design.
- **Adrian Mahn** — original MCP server code. Adrian built the first working ServiceNow MCP server that proved Claude could talk directly to a ServiceNow instance. This project extends his foundation with Chrome-based auth and domain-aware data generation.

Snowforge takes their ideas and wires them into a live MCP server — so instead of generating static scripts and hoping they work, Claude inspects the actual instance, creates records via API, and fixes issues in real-time.

---

## What it does

Tell Claude your industry, your customer name, and which modules you need. Snowforge builds:

- **CSDM foundation** — Business Capabilities → Business Services → Technical Services → Application Services → CIs (servers, databases, load balancers). Service maps render on the first try.
- **ITSM overlay** — Incidents, problems, changes, known errors with correct ratios and causal chains. Change-caused-incident stories baked in.
- **CSM overlay** — Accounts, contacts, cases with entitlements and SLAs.
- **HRSD overlay** — Lifecycle events, onboarding activities, HR cases with proper subtype handling.

Everything is prefixed (e.g. `SF-Acme-`) and cleanable with one command.

## Setup

### Prerequisites
- macOS with [Claude Desktop](https://claude.ai/download)
- Python 3.9+
- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Google Chrome

### Add to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "snowforge": {
      "command": "uv",
      "args": ["run", "--with", "mcp", "--with", "websockets", "python3", "/full/path/to/snowforge.mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop.

## Usage

1. **Connect**: "Connect to acmedemo" — Chrome opens to your instance
2. **Log in**: SSO/MFA/whatever your instance uses
3. **Say "ready"**: Claude extracts session cookies
4. **Generate**: "Generate CSDM + ITSM demo data for a healthcare company called MedTech Solutions"
5. **Clean up**: "Clean up all Snowforge data with prefix SF-MedTech"

## Tools

| Tool | Description |
|------|-------------|
| `connect_instance` | Launch Chrome to an SN instance for login |
| `complete_login` | Extract session cookies after login |
| `describe_table` | Get table schema (fields, types, required, references) |
| `list_records` | Query any table with filters and pagination |
| `get_record` | Get a single record by sys_id |
| `create_record` | Create a record in any table |
| `create_records_batch` | Create up to 50 records at once |
| `update_record` | Update a record |
| `delete_record` | Delete a record (confirms first) |
| `cleanup_by_prefix` | Delete all Snowforge-generated data by prefix |
| `run_script` | Execute a background script (server-side JS) |

## How it differs from SNODGE

SNODGE generates static JavaScript scripts that you paste into Background Scripts. Snowforge works **live**:

- Inspects the actual instance schema before creating records
- Finds real reference values (assignment groups, categories, CIs)
- Creates records via API and verifies they were created correctly
- Fixes issues in real-time instead of failing silently
- Uses your existing SSO session — no passwords in config files

The domain knowledge is the same — CSDM hierarchy, ITSM ratios, business rule gotchas — but the execution is interactive.

## License

MIT
