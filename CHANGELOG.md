# Changelog

## 0.2.0 — 2026-08-16

Production-hardening release.

### Added
- `read_output` tool: byte-offset pagination over `stdout.log`/`stderr.log`
  kept in a host-side work_dir by `run_command` or `start_process`.
- Dangerous-command safety filter (`rm -rf`, `mkfs`, `dd of=/dev/...`,
  `shutdown`/`reboot`/`halt`/`poweroff`, fork bombs, `DROP TABLE/DATABASE`);
  opt out per host with `allow_dangerous: true`. A seatbelt, not a boundary.
- `strict_host_key` per-host option: verify host keys against system
  `known_hosts` for both paramiko and rsync (default remains auto-accept).
- Audit logging of executed commands to stderr; MCP server `instructions`
  warning the model that commands hit real machines.

### Changed
- `run_command` now writes output to files on the remote host and returns at
  most 64 KiB per stream plus `stdout_bytes`/`stderr_bytes`/`truncated`/`work_dir`.
  This also removes the paramiko channel-window deadlock on multi-megabyte
  output. The work_dir is deleted when nothing was truncated.
- All remote executions honor `timeout` via an exit-status deadline; a hung
  command raises `TimeoutError` instead of blocking the tool call forever
  (the remote command may keep running).
- Remote output is decoded with `errors="replace"` so non-UTF-8 bytes cannot
  crash a tool call.
- `check_process` and `read_output` validate that `work_dir` matches
  `/tmp/bladerunner_mcp/<hex>`.

### Known limitations
- POSIX remote hosts only (`sh`, `nohup`, `tail`, `head`, `wc` required).
- No automatic retries on transient network errors; the tool call fails and
  can be retried by the caller.
- `check_process` can report a recycled PID as `running` (PID-reuse race).
- Password auth uses `sshpass` for rsync, which exposes the password in the
  local process list; prefer key auth.

## 0.1.0 — 2026-08-16

Initial PoC: `list_hosts`, `run_command`, `start_process`/`check_process`/
`kill_process` (nohup + PID + exit-code file), `put_file`/`get_file` via
rsync_ssh_client, YAML host config, docker compose e2e suite, CI.
