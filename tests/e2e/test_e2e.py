"""End-to-end tests against a docker compose sshd container: real exec, process tracking, rsync."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import paramiko
import pytest
import yaml

from bladerunner_mcp.server import (
    MAX_OUTPUT_BYTES,
    check_process,
    get_file,
    kill_process,
    list_hosts,
    put_file,
    read_output,
    run_command,
    start_process,
)

E2E_DIR = Path(__file__).parent
COMPOSE = ["docker", "compose", "-f", str(E2E_DIR / "docker-compose.yml")]

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_E2E") != "1" or shutil.which("docker") is None,
    reason="set RUN_E2E=1 with docker available",
)


@pytest.fixture(scope="session")
def sshd():
    keys = E2E_DIR / "keys"
    keys.mkdir(exist_ok=True)
    key = keys / "id_test"
    if not key.exists():
        subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    subprocess.run([*COMPOSE, "up", "-d", "--build"], check=True)
    try:
        out = subprocess.run(
            [*COMPOSE, "port", "sshd", "22"], check=True, capture_output=True, text=True
        ).stdout.strip()
        yield {"port": int(out.rsplit(":", 1)[1]), "key": str(key)}
    finally:
        subprocess.run([*COMPOSE, "down", "-v"], check=False)


@pytest.fixture
def host(sshd, tmp_path, monkeypatch):
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "hosts": {
                    "e2e": {
                        "host": "127.0.0.1",
                        "user": "test",
                        "port": sshd["port"],
                        "key_path": sshd["key"],
                    }
                }
            }
        )
    )
    monkeypatch.setenv("BLADERUNNER_MCP_CONFIG", str(config))
    for _ in range(30):
        try:
            if run_command("e2e", "true")["exit_code"] == 0:
                return "e2e"
        except (OSError, paramiko.SSHException):
            time.sleep(1)
    pytest.fail("sshd container did not become ready")


def test_list_hosts(host):
    assert list_hosts() == ["e2e"]


def test_run_command_streams_and_exit_code(host):
    result = run_command(host, "echo hello && echo oops >&2; exit 3")
    assert (result["stdout"], result["stderr"], result["exit_code"]) == ("hello\n", "oops\n", 3)
    assert result["truncated"] is False
    assert result["work_dir"] is None


def test_run_command_timeout(host):
    with pytest.raises(TimeoutError, match="did not finish"):
        run_command(host, "sleep 30", timeout=3)


def test_large_output_truncation_and_pagination(host):
    size = MAX_OUTPUT_BYTES * 2 + 12345
    result = run_command(host, f"head -c {size} /dev/zero | tr '\\0' a")
    assert result["truncated"] is True
    assert result["stdout_bytes"] == size
    assert len(result["stdout"].encode()) == MAX_OUTPUT_BYTES
    data, offset = "", 0
    while True:
        page = read_output(host, result["work_dir"], offset=offset)
        data += page["data"]
        offset += page["bytes"]
        if page["eof"]:
            break
    assert data == "a" * size


def test_small_output_work_dir_cleaned(host):
    count = "ls /tmp/bladerunner_mcp | wc -l"
    before = run_command(host, count)["stdout"].strip()
    result = run_command(host, "echo tidy")
    assert result["work_dir"] is None
    assert run_command(host, count)["stdout"].strip() == before


def test_process_lifecycle(host):
    started = start_process(host, "sleep 2; echo done")
    assert started["status"] == "running"
    result = started
    for _ in range(30):
        result = check_process(host, started["pid"], started["work_dir"])
        if result["status"] != "running":
            break
        time.sleep(1)
    assert (result["status"], result["exit_code"]) == ("succeeded", 0)
    assert "done" in result["stdout_tail"]


def test_process_failure_reports_exit_code(host):
    started = start_process(host, "echo bad >&2; exit 7")
    result = started
    for _ in range(30):
        result = check_process(host, started["pid"], started["work_dir"])
        if result["status"] != "running":
            break
        time.sleep(1)
    assert (result["status"], result["exit_code"]) == ("failed", 7)
    assert "bad" in result["stderr_tail"]


def test_kill_process(host):
    started = start_process(host, "sleep 300")
    assert kill_process(host, started["pid"])["killed"] is True
    time.sleep(1)
    assert check_process(host, started["pid"], started["work_dir"])["status"] != "running"


def test_file_roundtrip(host, tmp_path):
    src = tmp_path / "hello.txt"
    src.write_text("round trip\n")
    put_file(host, str(src), "/home/test/hello.txt")
    assert run_command(host, "cat /home/test/hello.txt")["stdout"] == "round trip\n"
    get_file(host, "/home/test/hello.txt", str(tmp_path / "down.txt"))
    assert (tmp_path / "down.txt").read_text() == "round trip\n"
