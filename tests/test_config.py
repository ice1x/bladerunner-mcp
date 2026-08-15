import pytest
import yaml

from bladerunner_mcp.server import Host, get_host, load_hosts


def test_load_hosts_parses_aliases(write_config, fake):
    ip, user = fake.ipv4(), fake.user_name()
    path = write_config(
        {"prod": {"host": ip, "user": user, "port": 2222, "key_path": "~/.ssh/id_ed25519"}}
    )
    assert load_hosts(path) == {
        "prod": Host(host=ip, user=user, port=2222, key_path="~/.ssh/id_ed25519")
    }


def test_load_hosts_defaults(write_config, fake):
    path = write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    host = load_hosts(path)["box"]
    assert (host.port, host.key_path, host.password) == (22, None, None)


def test_load_hosts_from_env_var(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    assert list(load_hosts()) == ["box"]


def test_load_hosts_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_hosts(str(tmp_path / "absent.yaml"))


def test_load_hosts_empty_file(tmp_path, monkeypatch):
    path = tmp_path / "empty.yaml"
    path.write_text("")
    assert load_hosts(str(path)) == {}


def test_load_hosts_password_auth(write_config, fake):
    password = fake.password()
    path = write_config(
        {"box": {"host": fake.ipv4(), "user": fake.user_name(), "password": password}}
    )
    assert load_hosts(path)["box"].password == password


def test_get_host_unknown_alias(write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    with pytest.raises(ValueError, match="Unknown host alias"):
        get_host("nope")


def test_write_config_yaml_roundtrip(write_config, fake):
    ip = fake.ipv4()
    path = write_config({"box": {"host": ip, "user": fake.user_name()}})
    with open(path) as f:
        assert yaml.safe_load(f)["hosts"]["box"]["host"] == ip
