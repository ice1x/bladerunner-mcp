# ssh_mcp

MCP server that lets an AI session operate your remote machines over SSH.

You `pip install ssh-mcp`, describe your hosts (e.g. a Hetzner box) in a config
file with credentials, and the server exposes MCP tools to execute commands and
transfer files on those hosts.

## Design

- Single short file built on **FastMCP** (`mcp` Python SDK).
- Command execution via **paramiko** (pattern proven in
  [blade_runner](https://github.com/ice1x/blade_runner) `SSHBackend`).
- File transfer via [rsync_ssh_client](https://github.com/ice1x/rsync_ssh_client)
  (`put` / `get` over rsync+SSH).
- Hosts and secrets come from a YAML config (`SSH_MCP_CONFIG` env var or
  `~/.ssh_mcp.yaml`); secrets never pass through the model.

### Planned tools

| Tool | Description |
|------|-------------|
| `list_hosts` | List configured host aliases (no secrets) |
| `run_command` | Execute a shell command on a host, return stdout/stderr/exit code |
| `put_file` | Upload a local path to a host via rsync |
| `get_file` | Download a remote path from a host via rsync |

### Example config

```yaml
# ssh_mcp.yaml
hosts:
  hetzner-prod:
    host: 203.0.113.10
    user: root
    port: 22
    key_path: ~/.ssh/id_ed25519
  legacy-box:
    host: 198.51.100.7
    user: deploy
    password: "use-key-auth-instead"   # sshpass fallback
```

## PoC tasks

- [ ] 1. Scaffold Python package (`pyproject.toml`, `ssh_mcp/server.py`) with `mcp` and `paramiko` dependencies and a `ssh-mcp` console entry point
- [ ] 2. Write unit tests for YAML host config loading (aliases, key/password auth, defaults, missing-file and unknown-alias errors)
- [ ] 3. Implement config loading: read hosts from `SSH_MCP_CONFIG` or `~/.ssh_mcp.yaml` into typed dataclasses
- [ ] 4. Write unit tests for `run_command` (mocked paramiko: stdout/stderr capture, exit code, timeout, connection error surfaced as tool error)
- [ ] 5. Implement FastMCP server with `list_hosts` and `run_command` tools using paramiko with per-call connect/close and timeout
- [ ] 6. Write unit tests for `put_file` / `get_file` (mocked `RsyncSSHClient`: correct config mapping, direction, error propagation)
- [ ] 7. Implement `put_file` / `get_file` tools on top of `rsync_ssh_client`
- [ ] 8. Add example config `ssh_mcp.example.yaml` to the repo
- [ ] 9. Add integration test against a local Docker `openssh-server` container (real exec + rsync round-trip)
- [ ] 10. Document installation and Claude Desktop / Claude Code MCP registration snippet in README
- [ ] 11. Set up CI (lint, type check, tests) and publish `ssh-mcp` to PyPI
