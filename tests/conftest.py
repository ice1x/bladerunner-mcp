from unittest.mock import MagicMock

import pytest
import yaml
from faker import Faker

from bladerunner_mcp import server


@pytest.fixture
def fake() -> Faker:
    Faker.seed(0)
    return Faker()


@pytest.fixture
def write_config(tmp_path, monkeypatch):
    """Write a hosts YAML config and point BLADERUNNER_MCP_CONFIG at it."""

    def _write(hosts: dict) -> str:
        path = tmp_path / "ssh_mcp.yaml"
        path.write_text(yaml.safe_dump({"hosts": hosts}))
        monkeypatch.setenv("BLADERUNNER_MCP_CONFIG", str(path))
        return str(path)

    return _write


def make_stream(data: bytes = b"", exit_code: int = 0) -> MagicMock:
    stream = MagicMock()
    stream.read.return_value = data
    stream.channel.recv_exit_status.return_value = exit_code
    return stream


@pytest.fixture
def ssh(monkeypatch):
    """Fake paramiko.SSHClient; queue (exit_code, stdout, stderr) tuples in .responses."""
    client = MagicMock()
    client.responses = []

    def exec_command(cmd, timeout=None):
        code, out, err = client.responses.pop(0) if client.responses else (0, b"", b"")
        return MagicMock(), make_stream(out, code), make_stream(err)

    client.exec_command.side_effect = exec_command
    monkeypatch.setattr(server.paramiko, "SSHClient", lambda: client)
    return client
