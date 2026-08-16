from subprocess import CalledProcessError
from unittest.mock import MagicMock

import pytest

from bladerunner_mcp import server


@pytest.fixture
def rsync(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(server, "RsyncSSHClient", mock)
    monkeypatch.setattr(server, "RETRY_DELAYS", (0, 0))
    return mock


@pytest.fixture
def host(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    return "box"


def test_transient_rsync_error_retried(rsync, host):
    rsync.return_value.put.side_effect = [CalledProcessError(10, "rsync"), "ok"]
    assert server.put_file(host, "a", "/srv/a") == "ok"
    assert rsync.return_value.put.call_count == 2


def test_ssh_failure_255_retried(rsync, host):
    rsync.return_value.get.side_effect = [CalledProcessError(255, "rsync"), "ok"]
    assert server.get_file(host, "/srv/a", "a") == "ok"
    assert rsync.return_value.get.call_count == 2


def test_permanent_rsync_error_not_retried(rsync, host):
    rsync.return_value.put.side_effect = CalledProcessError(23, "rsync")
    with pytest.raises(CalledProcessError):
        server.put_file(host, "a", "/srv/a")
    assert rsync.return_value.put.call_count == 1


def test_transient_errors_exhaust_retries(rsync, host):
    rsync.return_value.put.side_effect = CalledProcessError(30, "rsync")
    with pytest.raises(CalledProcessError):
        server.put_file(host, "a", "/srv/a")
    assert rsync.return_value.put.call_count == 3
