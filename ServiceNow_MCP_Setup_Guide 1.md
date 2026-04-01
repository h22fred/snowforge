# ServiceNow MCP Server — Setup Guide
Connect Claude Desktop to a ServiceNow instance for live read/write access via natural language.

---

## Prerequisites
- macOS (tested on Apple Silicon)
- [Claude Desktop](https://claude.ai/download) installed

---

## Step 1 — Install Python 3
Check if Python is already installed:
```bash
python3 --version
```
If not installed, download from [python.org](https://www.python.org/downloads/).

---

## Step 2 — Install uv (Python package runner)
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Close and reopen Terminal after installation.

---

## Step 3 — Save the MCP server script
Save the file `servicenow_mcp_server.py` (provided separately) to your home directory:
```
/Users/YOUR_USERNAME/servicenow_mcp_server.py
```

---

## Step 4 — Configure Claude Desktop
Open your Claude Desktop config file:
```bash
open -a TextEdit ~/Library/Application\ Support/Claude/claude_desktop_config.json
```

Replace the contents with the following (fill in your details):
```json
{
  "mcpServers": {
    "servicenow": {
      "command": "python3",
      "args": ["/Users/YOUR_USERNAME/servicenow_mcp_server.py"],
      "env": {
        "SN_INSTANCE_URL": "https://YOUR_INSTANCE.service-now.com",
        "SN_USERNAME": "YOUR_USERNAME",
        "SN_PASSWORD": "YOUR_PASSWORD"
      }
    }
  }
}
```

Replace:
- `YOUR_USERNAME` in the file path — your **Mac** username (e.g. `john.doe`). Find it by running `whoami` in Terminal.
- `YOUR_INSTANCE` — your ServiceNow instance name (e.g. `acmedemo`)
- `YOUR_USERNAME` / `YOUR_PASSWORD` in the env block — your **ServiceNow** admin credentials

---

## Step 5 — Restart Claude Desktop
Press **Cmd+Q** to fully quit Claude Desktop, then reopen it.

---

## Step 6 — Test the connection
In a new Claude Desktop chat, type:
> "List the 5 most recent incidents on my ServiceNow instance"

If you get back incident data, the connection is working! 🎉

---

## Available Commands
Once connected, Claude can:
- **Read** any table: "Show me all active GRC entities"
- **Create** records: "Create a new entity called X with owner Y"
- **Update** records: "Change the attestation method on these controls"
- **Delete** records: "Delete the test entity we just created"

---

## Troubleshooting

**"Server disconnected" error**
- Check that the file path in the config matches where you saved the script
- Make sure your ServiceNow password doesn't need special character escaping

**"Authentication failed (401)"**
- Verify your ServiceNow username and password are correct
- Check if MFA is enabled on the account — if so, disable it for the API user

**Tools not appearing in chat**
- Always start a **new conversation** after restarting Claude Desktop
- Tools only load at the start of a fresh chat

---

## Security Notes
- The config file contains your ServiceNow password in plain text — do not share it
- Use a dedicated API user with appropriate roles rather than your personal admin account for production use
- The MCP server only communicates between your local machine and your ServiceNow instance — no data passes through third-party servers
