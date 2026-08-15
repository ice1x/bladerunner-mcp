from unittest.mock import MagicMock

import pytest

from bladerunner_mcp import server


@pytest.fixture
def rsync(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr(server, "RsyncSSHClient", mock)
    return mock


@pytest.fixture
def host(write_config, fake):
    write_config(
        {
            "box": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "port": 2222,
                "key_path": "~/.ssh/id_test",
            }
        }
    )
    return "box"


def test_put_file_maps_config_and_direction(rsync, host):
    result = server.put_file(host, "build/", "/srv/app")
    config = rsync.call_args.args[0]
    assert config.ssh_port == 2222
    assert config.ssh_private_key.endswith("/.ssh/id_test")
    rsync.return_value.put.assert_called_once_with("build/", "/srv/app")
    assert result == rsync.return_value.put.return_value


def test_get_file_maps_direction(rsync, host):
    result = server.get_file(host, "/var/log/app", "logs/")
    rsync.return_value.get.assert_called_once_with("/var/log/app", "logs/")
    assert result == rsync.return_value.get.return_value


def test_password_host_enables_sshpass(rsync, write_config, fake):
    password = fake.password()
    write_config({"pw": {"host": fake.ipv4(), "user": fake.user_name(), "password": password}})
    server.put_file("pw", "a", "/b")
    config = rsync.call_args.args[0]
    assert config.password == password
    assert config.options.use_sshpass is True
    assert config.ssh_private_key is None


def test_transfer_error_propagates(rsync, host):
    rsync.return_value.put.side_effect = RuntimeError("rsync exited 23")
    with pytest.raises(RuntimeError, match="rsync exited 23"):
        server.put_file(host, "a", "/b")


def test_default_host_skips_host_key_checking(rsync, host):
    server.put_file(host, "a", "/b")
    options = rsync.call_args.args[0].options
    assert options.strict_host_key_checking == "no"
    assert options.user_known_hosts_file == "/dev/null"


def test_strict_host_enables_host_key_checking(rsync, write_config, fake):
    write_config(
        {
            "strict": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "strict_host_key": True,
            }
        }
    )
    server.put_file("strict", "a", "/b")
    options = rsync.call_args.args[0].options
    assert options.strict_host_key_checking == "yes"
    assert options.user_known_hosts_file is None
