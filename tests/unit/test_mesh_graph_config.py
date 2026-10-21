"""The mesh-graph start-up command writes a valid TOML file for any login.

`docker-compose.yml` starts mesh-graph with an awk program. It copies
`mesh-graph.config.toml` and writes the broker, the port and the login
into the copy as TOML basic strings. A basic string ends at the first
`"` and reads `\\` as the start of an escape (TOML 1.0, "String"). So a
password that holds either character made a broken file, or a file with
a different password or an extra key in it.

These tests run the exact awk program from the compose file. They take
it out of the YAML, so a change to the compose file is what is tested.
"""

import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
CONFIG = ROOT / "mesh-graph.config.toml"
OUTPUT = "/tmp/config.toml"
LOGIN = {
    "MQTT_HOST": "broker.example",
    "MQTT_PORT": "1883",
    "MQTT_USERNAME": "meshdev",
    "MQTT_PASSWORD": "p",
}

pytestmark = pytest.mark.skipif(shutil.which("awk") is None, reason="no awk")


def _awk_command() -> str:
    """The shell command that writes the config, before mesh-graph starts."""
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    command = services["mesh-graph"]["command"]
    assert len(command) == 1, "the mesh-graph command is not one `sh -c` string any more"
    # Compose reads `$$` as a literal `$`. The shell then sees `$`.
    script = command[0].replace("$$", "$")
    awk, separator, _ = script.partition(" && mesh-graph ")
    assert separator, "the command no longer starts mesh-graph after the awk step"
    assert f"/config.toml > {OUTPUT}" in awk
    return awk


def _write_config(tmp_path: Path, **environment: str) -> str:
    source = tmp_path / "config.toml"
    source.write_text(CONFIG.read_text(encoding="utf-8"), encoding="utf-8")
    target = tmp_path / "out.toml"
    awk = _awk_command().replace(f"> {OUTPUT}", f"> '{target}'")
    awk = awk.replace("/config.toml", f"'{source}'", 1)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **LOGIN, **environment}
    subprocess.run(["sh", "-c", awk], env=env, check=True, timeout=30)
    return target.read_text(encoding="utf-8")


def _mqtt(tmp_path: Path, **environment: str) -> dict:
    text = _write_config(tmp_path, **environment)
    try:
        return tomllib.loads(text)["mqtt"]
    except tomllib.TOMLDecodeError as error:
        pytest.fail(f"the command wrote a file that is not TOML ({error}):\n{text}")


def test_a_plain_login_is_written_as_given(tmp_path: Path) -> None:
    """The control: an ordinary login reaches the file unchanged."""
    mqtt = _mqtt(tmp_path, MQTT_PASSWORD="large4cats")
    assert mqtt["broker"] == "broker.example"
    assert mqtt["port"] == 1883
    assert mqtt["username"] == "meshdev"
    assert mqtt["password"] == "large4cats"


@pytest.mark.parametrize(
    "password",
    [
        'a"b',
        "a\\b",
        "ends with a backslash \\",
        '\\"',
        "\\n is two characters, not a new line",
    ],
)
def test_quotes_and_backslashes_in_a_password_are_kept(tmp_path: Path, password: str) -> None:
    mqtt = _mqtt(tmp_path, MQTT_PASSWORD=password)
    assert mqtt["password"] == password
    assert mqtt["username"] == "meshdev"


def test_a_password_cannot_add_a_key(tmp_path: Path) -> None:
    """Would be caught: escaping the quote and not the backslash.

    With only `"` escaped, `\\` in front of it escapes the escape, the
    string ends early, and the rest of the value is read as TOML.
    """
    password = '\\" , injected = "yes'
    mqtt = _mqtt(tmp_path, MQTT_PASSWORD=password)
    assert mqtt["password"] == password
    assert "injected" not in mqtt


def test_the_user_name_and_the_host_are_escaped_too(tmp_path: Path) -> None:
    mqtt = _mqtt(tmp_path, MQTT_HOST='broker"x', MQTT_USERNAME='me"\\', MQTT_PASSWORD="p")
    assert mqtt["broker"] == 'broker"x'
    assert mqtt["username"] == 'me"\\'


def test_a_port_that_is_not_a_number_stops_the_start(tmp_path: Path) -> None:
    """The port is written bare, so a value that is not a number is refused."""
    with pytest.raises(subprocess.CalledProcessError):
        _write_config(tmp_path, MQTT_PORT='1883 broker = "x"')
