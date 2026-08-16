from bladerunner_mcp.server import load_hosts, run_command
from tests.test_run_command import run_responses


def test_key_passphrase_parsed(write_config, fake):
    path = write_config(
        {
            "box": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "key_path": "~/.ssh/id_test",
                "key_passphrase": "s3cret",
            }
        }
    )
    assert load_hosts(path)["box"].key_passphrase == "s3cret"


def test_key_passphrase_defaults_none(write_config, fake):
    path = write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    assert load_hosts(path)["box"].key_passphrase is None


def test_connect_passes_passphrase(ssh, write_config, fake):
    write_config(
        {
            "box": {
                "host": fake.ipv4(),
                "user": fake.user_name(),
                "key_path": "~/.ssh/id_test",
                "key_passphrase": "s3cret",
            }
        }
    )
    ssh.responses = run_responses()
    run_command("box", "true")
    assert ssh.connect.call_args.kwargs["passphrase"] == "s3cret"


def test_connect_passphrase_none_by_default(ssh, write_config, fake):
    write_config({"box": {"host": fake.ipv4(), "user": fake.user_name()}})
    ssh.responses = run_responses()
    run_command("box", "true")
    assert ssh.connect.call_args.kwargs["passphrase"] is None
