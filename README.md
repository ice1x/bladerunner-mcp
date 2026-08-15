# bladerunner-mcp

MCP server that lets an AI session operate your remote machines over SSH.

You `pip install bladerunner-mcp`, describe your hosts (e.g. a Hetzner box) in a
YAML config with credentials, and the server exposes MCP tools to run commands,
track long-running processes and transfer files on those hosts. The model only
ever sees host aliases — secrets never enter the conversation.

## Tools

| Tool | Description |
|------|-------------|
| `list_hosts` | List configured host aliases (no secrets) |
| `run_command` | Run a shell command on a host, return stdout/stderr/exit code |
| `start_process` | Start a long-running command in the background (nohup), return pid + work_dir |
| `check_process` | Report process status (`running`/`succeeded`/`failed`/`unknown`), exit code and log tails |
| `kill_process` | Kill a background process |
| `put_file` | Upload a local path to a host via rsync |
| `get_file` | Download a remote path from a host via rsync |

## Installation

```bash
pip install bladerunner-mcp
```

## Configuration

Copy [bladerunner_mcp.example.yaml](bladerunner_mcp.example.yaml) to
`~/.bladerunner_mcp.yaml` (or set `BLADERUNNER_MCP_CONFIG` to its path):

```yaml
hosts:
  hetzner-prod:
    host: 203.0.113.10
    user: root
    port: 22
    key_path: ~/.ssh/id_ed25519
```

## Register with a client

Claude Code:

```bash
claude mcp add bladerunner -- bladerunner-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bladerunner": {
      "command": "bladerunner-mcp",
      "env": { "BLADERUNNER_MCP_CONFIG": "/Users/me/.bladerunner_mcp.yaml" }
    }
  }
}
```

## Design

- One short file ([bladerunner_mcp/server.py](bladerunner_mcp/server.py)) built on
  `MCPServer` from the official `mcp` Python SDK.
- Command execution via **paramiko**; background processes follow the
  nohup + PID + exit-code-file pattern proven in
  [blade_runner](https://github.com/ice1x/blade_runner)'s `SSHBackend`
  (the AI session itself plays the role of the polling monitor, so the full FSM
  is not embedded).
- File transfer via [rsync_ssh_client](https://github.com/ice1x/rsync_ssh_client)
  (`put` / `get` over rsync+SSH, sshpass fallback for password auth).

## Development

```bash
pip install -e ".[dev]"
pytest                      # unit tests (mocked paramiko/rsync)
RUN_E2E=1 pytest tests/e2e  # e2e against a docker compose sshd container
ruff check . && mypy bladerunner_mcp
```

## PoC tasks

- [x] 1. Scaffold Python package (`pyproject.toml`, `bladerunner_mcp/server.py`) with `mcp` and `paramiko` dependencies and a `bladerunner-mcp` console entry point
- [x] 2. Write unit tests for YAML host config loading (aliases, key/password auth, defaults, missing-file and unknown-alias errors)
- [x] 3. Implement config loading: read hosts from `BLADERUNNER_MCP_CONFIG` or `~/.bladerunner_mcp.yaml` into typed dataclasses
- [x] 4. Write unit tests for `run_command` (mocked paramiko: stdout/stderr capture, exit code, connection error surfaced as tool error)
- [x] 5. Implement MCP server with `list_hosts` and `run_command` tools using paramiko with per-call connect/close and timeout
- [x] 6. Write unit tests for background process tools (start/check/kill, mocked paramiko)
- [x] 7. Implement `start_process` / `check_process` / `kill_process` reusing blade_runner's nohup + PID + exit-code-file pattern
- [x] 8. Write unit tests for `put_file` / `get_file` (mocked `RsyncSSHClient`: config mapping, direction, error propagation)
- [x] 9. Implement `put_file` / `get_file` tools on top of `rsync_ssh_client`
- [x] 10. Add example config `bladerunner_mcp.example.yaml` to the repo
- [x] 11. Add e2e tests against a docker compose sshd container (real exec, process lifecycle, rsync round-trip)
- [x] 12. Document installation and Claude Desktop / Claude Code MCP registration in README
- [x] 13. Set up CI (ruff, mypy, unit tests, e2e) via GitHub Actions
- [ ] 14. Publish `bladerunner-mcp` to PyPI (trusted-publishing workflow is in place; needs a PyPI project + `pypi` environment configured on GitHub)
