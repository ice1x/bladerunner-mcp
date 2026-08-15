# bladerunner-mcp

MCP server that lets an AI session operate your remote machines over SSH.

> ⚠️ **These tools run real commands on real servers with your credentials.**
> Running your MCP client in auto-approve ("YOLO") mode means the model can
> execute anything on your machines without you seeing it first. Keep manual
> approval on for this server, use least-privilege SSH accounts, and have
> backups/snapshots for anything you point it at. See [Security](#security).

You `pip install bladerunner-mcp`, describe your hosts (e.g. a Hetzner box) in a
YAML config with credentials, and the server exposes MCP tools to run commands,
track long-running processes and transfer files on those hosts. The model only
ever sees host aliases — secrets never enter the conversation.

**Scope:** POSIX remote hosts only (`sh`, `nohup`, `tail`, `head`, `wc` must be
present on the target). Windows hosts are not supported.

## Tools

| Tool | Description |
|------|-------------|
| `list_hosts` | List configured host aliases (no secrets) |
| `run_command` | Run a shell command on a host, return stdout/stderr/exit code (capped at 64 KiB per stream) |
| `read_output` | Page through the full output of a truncated `run_command` or a background process |
| `start_process` | Start a long-running command in the background (nohup), return pid + work_dir |
| `check_process` | Report process status (`running`/`succeeded`/`failed`/`unknown`), exit code and log tails |
| `kill_process` | Kill a background process |
| `put_file` | Upload a local path to a host via rsync |
| `get_file` | Download a remote path from a host via rsync |

Large outputs: `run_command` keeps the full output on the host (in a `work_dir`
under `/tmp/bladerunner_mcp/`) whenever it exceeds the 64 KiB cap and returns
`truncated: true` — page through it with `read_output(host, work_dir, offset=...)`.

## Installation

```bash
pip install bladerunner-mcp
```

## Configuration

Copy [bladerunner_mcp.example.yaml](https://github.com/ice1x/bladerunner-mcp/blob/main/bladerunner_mcp.example.yaml) to
`~/.bladerunner_mcp.yaml` (or set `BLADERUNNER_MCP_CONFIG` to its path):

```yaml
hosts:
  hetzner-prod:
    host: 203.0.113.10
    user: root
    port: 22
    key_path: ~/.ssh/id_ed25519
    strict_host_key: true    # verify against system known_hosts (default: false)
    allow_dangerous: false   # keep the dangerous-command filter on (default)
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

## Security

- **Do not run your MCP client in auto-approve ("YOLO") mode with this server.**
  Every `run_command`/`start_process` call is a real shell on a real machine;
  keep per-call approval on so you see each command before it runs.
- **Dangerous-command filter** — commands matching obviously catastrophic
  patterns (`rm -rf`, `mkfs`, `dd of=/dev/...`, `shutdown`/`reboot`, fork bombs,
  `DROP TABLE/DATABASE`) are rejected by default. This is a seatbelt against
  accidents, **not** a security boundary: any denylist is bypassable by a
  determined caller. Disable per host with `allow_dangerous: true`.
- **Least privilege** — point the server at dedicated SSH accounts with the
  minimum rights the task needs, not at `root`, and keep backups/snapshots of
  anything it can touch.
- **Host keys** — by default unknown host keys are auto-accepted (convenient,
  MITM-unsafe). Set `strict_host_key: true` per host to verify against your
  system `known_hosts` (applies to both paramiko and rsync).
- **Auth** — prefer SSH keys. Password auth works (rsync falls back to
  `sshpass`, which exposes the password in the local process list) and the
  password sits in plaintext YAML; treat it as legacy-host escape hatch only.
- **Secrets stay local** — the model sees host aliases only; keys and passwords
  never enter the conversation. Executed commands are logged to stderr for audit.

## Design

- One short file ([bladerunner_mcp/server.py](https://github.com/ice1x/bladerunner-mcp/blob/main/bladerunner_mcp/server.py)) built on
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
- [x] 14. Cap `run_command` output per stream and add `read_output` pagination over host-side work_dir files
- [x] 15. Add execution timeout (deadline poll on exit status) so hung commands fail instead of blocking forever
- [x] 16. Decode remote output with `errors="replace"` and validate `work_dir` tool arguments
- [x] 17. Add `strict_host_key` per-host option (system known_hosts for both paramiko and rsync)
- [x] 18. Add dangerous-command safety filter with per-host `allow_dangerous` opt-out
- [x] 19. Add audit logging of executed commands to stderr and YOLO-mode warning (README + server instructions)
- [x] 20. Retry transient SSH connection errors (3 attempts with backoff; auth/host-key errors fail fast)
- [x] 21. Fix PID-reuse race: liveness matched on the process command line (`ps -p -o args=` with `/proc` fallback), not bare `kill -0`
- [x] 22. Cap `check_process` log tails by bytes and polish PyPI metadata (classifiers, keywords, project URLs)
- [ ] 23. Publish `bladerunner-mcp` to PyPI (trusted-publishing workflow is in place; needs a PyPI project + `pypi` environment configured on GitHub)
