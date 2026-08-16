[![PyPI](https://img.shields.io/pypi/v/bladerunner-mcp)](https://pypi.org/project/bladerunner-mcp/)
[![PyPI - Downloads](https://img.shields.io/pypi/dm/bladerunner-mcp)](https://pypistats.org/packages/bladerunner-mcp)
[![Python](https://img.shields.io/pypi/pyversions/bladerunner-mcp)](https://pypi.org/project/bladerunner-mcp/)
[![License](https://img.shields.io/pypi/l/bladerunner-mcp)](https://github.com/ice1x/bladerunner-mcp/blob/main/LICENSE)
[![CI](https://github.com/ice1x/bladerunner-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/ice1x/bladerunner-mcp/actions/workflows/ci.yml)

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
    # key_passphrase: "..."  # for passphrase-protected keys (commands only)
    strict_host_key: true    # verify against system known_hosts (default: false)
    allow_dangerous: false   # keep the safety filters on (default)
    # protected_paths: [/etc, /var/lib]               # override the default protected list
    # allowed_remote_paths: [/srv/app, /var/log/app]  # opt-in transfer allowlist
    # allowed_local_paths: [~/deploys]
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
- **Protected-path filter (commands)** — mutating operations (`rm`, `mv`,
  `chmod`, `chown`, `shred`, `truncate`, `chattr`, `sed -i`, `tee`, output
  redirects, and `cp`/`rsync`/`install`/`ln` writing into them) on system paths (`/`, `/etc`, `/boot`, `/bin`, `/sbin`, `/usr`,
  `/lib*`, `/dev`, `/sys`, `/proc`, `/root`, `/var/lib`) are rejected; reads of
  the same paths and mutations elsewhere pass. Catastrophic non-path patterns
  (`mkfs`, `dd of=/dev/...`, `shutdown`/`reboot`, fork bombs,
  `DROP TABLE/DATABASE`) are also rejected. Override with per-host
  `protected_paths`. This is a seatbelt against accidents, **not** a security
  boundary: shell is not statically analyzable. Disable per host with
  `allow_dangerous: true`.
- **Path validation (transfers)** — `put_file`/`get_file` paths are expanded
  and normalized (`..` resolved) and then enforced for real: protected system
  prefixes are denied on the remote side, and `~/.ssh`, `~/.gnupg`,
  `~/Library/Keychains` plus system dirs on the local side (both directions —
  exfiltrating local keys is as bad as overwriting them). Optional per-host
  `allowed_remote_paths` / `allowed_local_paths` restrict transfers to listed
  prefixes. Remote symlinks are not resolved (known limit).
- **Least privilege** — point the server at dedicated SSH accounts with the
  minimum rights the task needs, not at `root`, and keep backups/snapshots of
  anything it can touch.
- **Host keys** — by default unknown host keys are auto-accepted (convenient,
  MITM-unsafe). Set `strict_host_key: true` per host to verify against your
  system `known_hosts` (applies to both paramiko and rsync).
- **Auth** — prefer SSH keys; passphrase-protected keys work for command
  tools via `key_passphrase` (transfers need an agent-loaded or plain key).
  Password auth works (rsync falls back to
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
