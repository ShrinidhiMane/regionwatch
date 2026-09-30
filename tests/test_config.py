import pytest

from regionwatch.config import ConfigError, load_settings, parse_settings

from .conftest import make_raw


def test_valid_config_parses():
    s = parse_settings(make_raw())
    assert len(s.targets) == 2
    east = s.targets[0]
    assert east.remediation.action == "webhook"
    assert east.remediation.max_attempts == 2
    assert s.targets[1].remediation.action == "none"


def test_duplicate_ids_rejected():
    raw = make_raw()
    raw["targets"].append(dict(raw["targets"][0]))
    with pytest.raises(ConfigError, match="duplicate"):
        parse_settings(raw)


def test_missing_url_rejected():
    raw = make_raw(targets=[{"id": "x", "region": "r"}])
    with pytest.raises(ConfigError, match="url"):
        parse_settings(raw)


def test_unknown_action_rejected():
    raw = make_raw(targets=[{"id": "x", "region": "r", "url": "http://x",
                             "remediation": {"action": "reboot_the_world"}}])
    with pytest.raises(ConfigError, match="unknown remediation"):
        parse_settings(raw)


def test_docker_restart_needs_container():
    raw = make_raw(targets=[{"id": "x", "region": "r", "url": "http://x",
                             "remediation": {"action": "docker_restart"}}])
    with pytest.raises(ConfigError, match="container"):
        parse_settings(raw)


def test_no_targets_rejected():
    with pytest.raises(ConfigError, match="at least one"):
        parse_settings(make_raw(targets=[]))


def test_bundled_config_files_are_valid():
    for name in ("config/targets.local.yaml", "config/targets.docker.yaml"):
        assert load_settings(name).targets


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_settings(tmp_path / "nope.yaml")
