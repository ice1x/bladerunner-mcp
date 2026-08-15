"""MCP server exposing SSH command execution, background process control and rsync file transfer.

Hosts and secrets live in a YAML config (BLADERUNNER_MCP_CONFIG env var or ~/.bladerunner_mcp.yaml);
the model only ever sees host aliases. Command execution uses paramiko, background
processes follow the nohup + PID + exit-code-file pattern from blade_runner's
SSHBackend, file transfer reuses rsync_ssh_client.
"""

import os
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import paramiko
import yaml
from mcp.server import MCPServer
from rsync_ssh_client import RsyncConfig, RsyncOptions, RsyncSSHClient

DEFAULT_CONFIG_PATH = "~/.bladerunner_mcp.yaml"
LOG_TAIL_LINES = 50


@dataclass(frozen=True)
class Host:
    host: str
    user: str
    port: int = 22
    key_path: str | None = None
    password: str | None = None


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


def _connect(spec: Host, timeout: float) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
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


def _exec(client: paramiko.SSHClient, command: str) -> tuple[int, str, str]:
    _stdin, stdout, stderr = client.exec_command(command)
    exit_code = stdout.channel.recv_exit_status()
    return exit_code, stdout.read().decode(), stderr.read().decode()


mcp = MCPServer("bladerunner_mcp")


@mcp.tool()
def list_hosts() -> list[str]:
    """List configured host aliases."""
    return sorted(load_hosts())


@mcp.tool()
def run_command(host: str, command: str, timeout: float = 60.0) -> dict[str, Any]:
    """Run a shell command on a configured host and return stdout, stderr and exit code."""
    client = _connect(get_host(host), timeout)
    try:
        exit_code, out, err = _exec(client, command)
        return {"stdout": out, "stderr": err, "exit_code": exit_code}
    finally:
        client.close()


@mcp.tool()
def start_process(host: str, command: str, timeout: float = 30.0) -> dict[str, Any]:
    """Start a long-running command on a host in the background.

    Returns pid and work_dir; pass both to check_process to track it.
    """
    work_dir = f"/tmp/bladerunner_mcp/{uuid.uuid4().hex[:12]}"
    # Subshell so that `exit` in the command cannot skip the exit-code capture
    script = f"({command})\necho $? > {work_dir}/exit_code\n"
    client = _connect(get_host(host), timeout)
    try:
        exit_code, _out, err = _exec(
            client, f"mkdir -p {work_dir} && printf '%s' {shlex.quote(script)} > {work_dir}/run.sh"
        )
        if exit_code != 0:
            raise RuntimeError(f"Failed to prepare work dir: {err}")
        _code, out, err = _exec(
            client,
            f"nohup sh {work_dir}/run.sh > {work_dir}/stdout.log 2> {work_dir}/stderr.log & echo $!",
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
    client = _connect(get_host(host), timeout)
    try:
        alive_code, _, _ = _exec(client, f"kill -0 {pid} 2>/dev/null")
        _, exit_out, _ = _exec(client, f"cat {work_dir}/exit_code 2>/dev/null")
        _, out_tail, _ = _exec(
            client, f"tail -n {LOG_TAIL_LINES} {work_dir}/stdout.log 2>/dev/null"
        )
        _, err_tail, _ = _exec(
            client, f"tail -n {LOG_TAIL_LINES} {work_dir}/stderr.log 2>/dev/null"
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
    client = _connect(get_host(host), timeout)
    try:
        exit_code, _, err = _exec(client, f"kill -9 {pid}")
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
            options=RsyncOptions(use_sshpass=spec.password is not None),
        )
    )


@mcp.tool()
def put_file(host: str, local_path: str, remote_path: str) -> str:
    """Upload a local file or directory to a configured host via rsync."""
    return _rsync(get_host(host)).put(local_path, remote_path)


@mcp.tool()
def get_file(host: str, remote_path: str, local_path: str) -> str:
    """Download a file or directory from a configured host via rsync."""
    return _rsync(get_host(host)).get(remote_path, local_path)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
