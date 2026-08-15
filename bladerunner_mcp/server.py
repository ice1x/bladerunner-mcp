"""MCP server exposing SSH command execution, background process control and rsync file transfer.

Hosts and secrets live in a YAML config (BLADERUNNER_MCP_CONFIG env var or
~/.bladerunner_mcp.yaml); the model only ever sees host aliases. Command execution
uses paramiko, background processes follow the nohup + PID + exit-code-file pattern
from blade_runner's SSHBackend, file transfer reuses rsync_ssh_client.

POSIX remote hosts only: the tools rely on sh, nohup, tail, head and wc being
present on the target. Windows hosts are not supported.
"""

import logging
import os
import re
import shlex
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paramiko
import yaml
from mcp.server import MCPServer
from rsync_ssh_client import RsyncConfig, RsyncOptions, RsyncSSHClient

DEFAULT_CONFIG_PATH = "~/.bladerunner_mcp.yaml"
WORK_DIR_ROOT = "/tmp/bladerunner_mcp"
MAX_OUTPUT_BYTES = 65536
LOG_TAIL_LINES = 50
POLL_INTERVAL = 0.05

INSTRUCTIONS = (
    "These tools run real commands on the user's remote machines with the user's "
    "credentials. Mistakes are not sandboxed: a destructive command damages a real "
    "server. Prefer read-only commands, be conservative with anything that mutates "
    "state, and never run destructive commands (rm -rf, mkfs, dd, DROP TABLE, "
    "shutdown) unless the user explicitly asked for that exact action."
)

logger = logging.getLogger("bladerunner_mcp")

# Seatbelt against obviously catastrophic commands, not a security boundary:
# any denylist is bypassable. Disable per host with allow_dangerous: true.
DENY_PATTERNS = [
    r"rm\s+(-+[a-zA-Z-]+\s+)*-+[a-zA-Z]*[rR][a-zA-Z]*[fF]",
    r"rm\s+(-+[a-zA-Z-]+\s+)*-+[a-zA-Z]*[fF][a-zA-Z]*[rR]",
    r"\bmkfs",
    r"\bdd\s+[^|;&]*of=/dev/",
    r"\b(shutdown|reboot|halt|poweroff)\b",
    r":\(\)\s*\{",
    r"\bdrop\s+(table|database)\b",
]


@dataclass(frozen=True)
class Host:
    host: str
    user: str
    port: int = 22
    key_path: str | None = None
    password: str | None = None
    strict_host_key: bool = False
    allow_dangerous: bool = False


def load_hosts(path: str | None = None) -> dict[str, Host]:
    config_path = Path(
        path or os.environ.get("BLADERUNNER_MCP_CONFIG") or DEFAULT_CONFIG_PATH
    ).expanduser()
    if not config_path.exists():
        raise FileNotFoundError(f"Host config not found: {config_path}")
    data = yaml.safe_load(config_path.read_text()) or {}
    return {alias: Host(**spec) for alias, spec in (data.get("hosts") or {}).items()}


def get_host(alias: str) -> Host:
    hosts = load_hosts()
    if alias not in hosts:
        raise ValueError(f"Unknown host alias {alias!r}, known: {sorted(hosts)}")
    return hosts[alias]


def _expand(path: str | None) -> str | None:
    return str(Path(path).expanduser()) if path else None


def _check_command(command: str, spec: Host) -> None:
    if spec.allow_dangerous:
        return
    for pattern in DENY_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            raise ValueError(
                f"Command blocked by safety filter (matched {pattern!r}). "
                "Set allow_dangerous: true for this host to disable the filter."
            )


def _new_work_dir() -> str:
    return f"{WORK_DIR_ROOT}/{uuid.uuid4().hex[:12]}"


def _validate_work_dir(work_dir: str) -> str:
    if not re.fullmatch(f"{WORK_DIR_ROOT}/[0-9a-f]+", work_dir):
        raise ValueError(f"work_dir must match {WORK_DIR_ROOT}/<hex id>, got {work_dir!r}")
    return work_dir


def _connect(spec: Host, timeout: float) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    if spec.strict_host_key:
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
    else:
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=spec.host,
            port=spec.port,
            username=spec.user,
            key_filename=_expand(spec.key_path),
            password=spec.password,
            timeout=timeout,
        )
    except Exception:
        client.close()
        raise
    return client


def _exec(
    client: paramiko.SSHClient, command: str, timeout: float | None = None
) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    channel = stdout.channel
    deadline = time.monotonic() + timeout if timeout else None
    while not channel.exit_status_ready():
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError(
                f"Remote command did not finish within {timeout}s (it may still be running)"
            )
        time.sleep(POLL_INTERVAL)
    exit_code = channel.recv_exit_status()
    return exit_code, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")


mcp = MCPServer("bladerunner_mcp", instructions=INSTRUCTIONS)


@mcp.tool()
def list_hosts() -> list[str]:
    """List configured host aliases."""
    return sorted(load_hosts())


@mcp.tool()
def run_command(host: str, command: str, timeout: float = 60.0) -> dict[str, Any]:
    """Run a shell command on a configured host and return stdout, stderr and exit code.

    Each stream is capped at MAX_OUTPUT_BYTES. If truncated, the full output stays
    on the host in work_dir — page through it with read_output. On timeout the
    remote command may keep running.
    """
    logger.info("run_command host=%s command=%r", host, command)
    spec = get_host(host)
    _check_command(command, spec)
    work_dir = _new_work_dir()
    client = _connect(spec, timeout)
    try:
        header_cmd = (
            f"mkdir -p {work_dir} && "
            f"( {command} ) > {work_dir}/stdout.log 2> {work_dir}/stderr.log; "
            f"echo $?; wc -c < {work_dir}/stdout.log; wc -c < {work_dir}/stderr.log"
        )
        _code, header, err = _exec(client, header_cmd, timeout)
        try:
            exit_code, stdout_bytes, stderr_bytes = (int(line) for line in header.split())
        except ValueError as exc:
            raise RuntimeError(f"Failed to run command: {err or header}") from exc
        _, out_head, _ = _exec(client, f"head -c {MAX_OUTPUT_BYTES} {work_dir}/stdout.log", timeout)
        _, err_head, _ = _exec(client, f"head -c {MAX_OUTPUT_BYTES} {work_dir}/stderr.log", timeout)
        truncated = stdout_bytes > MAX_OUTPUT_BYTES or stderr_bytes > MAX_OUTPUT_BYTES
        if not truncated:
            _exec(client, f"rm -rf {work_dir}", timeout)
        return {
            "stdout": out_head,
            "stderr": err_head,
            "exit_code": exit_code,
            "stdout_bytes": stdout_bytes,
            "stderr_bytes": stderr_bytes,
            "truncated": truncated,
            "work_dir": work_dir if truncated else None,
        }
    finally:
        client.close()


@mcp.tool()
def read_output(
    host: str,
    work_dir: str,
    stream: str = "stdout",
    offset: int = 0,
    length: int = MAX_OUTPUT_BYTES,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Read a byte slice of stdout/stderr kept in a work_dir by run_command or start_process."""
    _validate_work_dir(work_dir)
    if stream not in ("stdout", "stderr"):
        raise ValueError(f"stream must be 'stdout' or 'stderr', got {stream!r}")
    offset = max(0, offset)
    length = max(0, min(length, MAX_OUTPUT_BYTES))
    path = f"{work_dir}/{stream}.log"
    client = _connect(get_host(host), timeout)
    try:
        exit_code, total_out, err = _exec(client, f"wc -c < {path}", timeout)
        if exit_code != 0:
            raise RuntimeError(f"Cannot read {path}: {err.strip()}")
        total_bytes = int(total_out.strip())
        _, data, _ = _exec(client, f"tail -c +{offset + 1} {path} | head -c {length}", timeout)
        returned = min(length, max(0, total_bytes - offset))
        return {
            "data": data,
            "offset": offset,
            "bytes": returned,
            "total_bytes": total_bytes,
            "eof": offset + returned >= total_bytes,
        }
    finally:
        client.close()


@mcp.tool()
def start_process(host: str, command: str, timeout: float = 30.0) -> dict[str, Any]:
    """Start a long-running command on a host in the background.

    Returns pid and work_dir; pass both to check_process to track it,
    and use read_output to page through its logs.
    """
    logger.info("start_process host=%s command=%r", host, command)
    spec = get_host(host)
    _check_command(command, spec)
    work_dir = _new_work_dir()
    # Subshell so that `exit` in the command cannot skip the exit-code capture
    script = f"({command})\necho $? > {work_dir}/exit_code\n"
    client = _connect(spec, timeout)
    try:
        exit_code, _out, err = _exec(
            client,
            f"mkdir -p {work_dir} && printf '%s' {shlex.quote(script)} > {work_dir}/run.sh",
            timeout,
        )
        if exit_code != 0:
            raise RuntimeError(f"Failed to prepare work dir: {err}")
        _code, out, err = _exec(
            client,
            f"nohup sh {work_dir}/run.sh > {work_dir}/stdout.log 2> {work_dir}/stderr.log & echo $!",
            timeout,
        )
        try:
            pid = int(out.strip())
        except ValueError as exc:
            raise RuntimeError(f"Failed to start process: {err or out}") from exc
        return {"pid": pid, "work_dir": work_dir, "status": "running"}
    finally:
        client.close()


@mcp.tool()
def check_process(host: str, pid: int, work_dir: str, timeout: float = 30.0) -> dict[str, Any]:
    """Check a process started with start_process: status, exit code and log tails."""
    _validate_work_dir(work_dir)
    client = _connect(get_host(host), timeout)
    try:
        alive_code, _, _ = _exec(client, f"kill -0 {pid} 2>/dev/null", timeout)
        _, exit_out, _ = _exec(client, f"cat {work_dir}/exit_code 2>/dev/null", timeout)
        _, out_tail, _ = _exec(
            client, f"tail -n {LOG_TAIL_LINES} {work_dir}/stdout.log 2>/dev/null", timeout
        )
        _, err_tail, _ = _exec(
            client, f"tail -n {LOG_TAIL_LINES} {work_dir}/stderr.log 2>/dev/null", timeout
        )
        if alive_code == 0:
            status, exit_code = "running", None
        elif exit_out.strip().isdigit():
            exit_code = int(exit_out.strip())
            status = "succeeded" if exit_code == 0 else "failed"
        else:
            status, exit_code = "unknown", None
        return {
            "status": status,
            "exit_code": exit_code,
            "stdout_tail": out_tail,
            "stderr_tail": err_tail,
        }
    finally:
        client.close()


@mcp.tool()
def kill_process(host: str, pid: int, timeout: float = 30.0) -> dict[str, Any]:
    """Kill a process started with start_process (SIGKILL)."""
    logger.info("kill_process host=%s pid=%s", host, pid)
    client = _connect(get_host(host), timeout)
    try:
        exit_code, _, err = _exec(client, f"kill -9 {pid}", timeout)
        return {"killed": exit_code == 0, "detail": err.strip()}
    finally:
        client.close()


def _rsync(spec: Host) -> "RsyncSSHClient":
    return RsyncSSHClient(
        RsyncConfig(
            user=spec.user,
            host=spec.host,
            ssh_port=spec.port,
            ssh_private_key=_expand(spec.key_path),
            password=spec.password,
            options=RsyncOptions(
                use_sshpass=spec.password is not None,
                strict_host_key_checking="yes" if spec.strict_host_key else "no",
                user_known_hosts_file=None if spec.strict_host_key else "/dev/null",
            ),
        )
    )


@mcp.tool()
def put_file(host: str, local_path: str, remote_path: str) -> str:
    """Upload a local file or directory to a configured host via rsync."""
    logger.info("put_file host=%s local=%s remote=%s", host, local_path, remote_path)
    return _rsync(get_host(host)).put(local_path, remote_path)


@mcp.tool()
def get_file(host: str, remote_path: str, local_path: str) -> str:
    """Download a file or directory from a configured host via rsync."""
    logger.info("get_file host=%s remote=%s local=%s", host, remote_path, local_path)
    return _rsync(get_host(host)).get(remote_path, local_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    mcp.run()


if __name__ == "__main__":
    main()
