"""Freeze the current configuration and deployment contracts without external I/O."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic_settings import SettingsError

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = (
    ROOT
    / "tests"
    / "fixtures"
    / "characterization"
    / "configuration_deployment_contract.json"
)


def _contract() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _clear_settings_env(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    for name in names:
        monkeypatch.delenv(name, raising=False)


def _env_example_names(text: str) -> tuple[list[str], list[str]]:
    declared: set[str] = set()
    active: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^\s*(#\s*)?([A-Z][A-Z0-9_]*)\s*=", line)
        if not match:
            continue
        name = match.group(2)
        declared.add(name)
        if match.group(1) is None:
            active.add(name)
    return sorted(declared), sorted(active)


def _dockerfile_instructions(text: str) -> list[str]:
    instructions: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        instructions.append(pending)
        pending = ""
    if pending:
        instructions.append(pending)
    return instructions


def test_settings_names_defaults_and_model_config_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.config import Settings

    expected = _contract()["settings"]
    _clear_settings_env(monkeypatch, expected["env_names"])

    settings = Settings(_env_file=None)

    assert sorted(name.upper() for name in Settings.model_fields) == expected["env_names"]
    assert settings.model_dump(mode="json") == expected["defaults"]
    assert Settings.model_config["env_file"] == expected["model_config"]["env_file"]
    assert Settings.model_config["env_file_encoding"] == "utf-8"
    assert Settings.model_config["case_sensitive"] is False
    assert Settings.model_config["extra"] == "ignore"


def test_settings_precedence_is_init_then_environment_then_dotenv_then_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from xhs_food.config import Settings

    expected = _contract()["settings"]
    _clear_settings_env(monkeypatch, expected["env_names"])
    env_file = tmp_path / ".env"
    env_file.write_text("API_PORT=7100\nUNKNOWN_LEGACY_KEY=ignored\n", encoding="utf-8")

    assert Settings(_env_file=None).api_port == 8000
    assert Settings(_env_file=env_file).api_port == 7100

    monkeypatch.setenv("API_PORT", "7200")
    assert Settings(_env_file=env_file).api_port == 7200
    assert Settings(api_port=7300, _env_file=env_file).api_port == 7300
    assert expected["precedence_high_to_low"] == [
        "init_kwargs",
        "process_environment",
        "dotenv_file",
        "field_default",
    ]


def test_env_example_names_and_known_parser_conflicts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.config import Settings

    contract = _contract()
    expected = contract["env_example"]
    settings_names = set(contract["settings"]["env_names"])
    text = (ROOT / expected["source"]).read_text(encoding="utf-8")
    declared, active = _env_example_names(text)

    assert declared == expected["declared_names"]
    assert active == expected["active_names"]
    assert sorted(settings_names - set(declared)) == expected["settings_only_names"]
    assert sorted(set(declared) - settings_names) == expected["env_example_only_names"]

    _clear_settings_env(monkeypatch, contract["settings"]["env_names"])
    monkeypatch.setenv("SSE_TIMEOUT", "111")
    assert Settings(_env_file=None).sse_timeout_seconds == 900
    monkeypatch.setenv("SSE_TIMEOUT_SECONDS", "222")
    assert Settings(_env_file=None).sse_timeout_seconds == 222

    monkeypatch.setenv("CORS_ORIGINS", "http://one.example,http://two.example")
    with pytest.raises(SettingsError, match="cors_origins"):
        Settings(_env_file=None)


@pytest.mark.parametrize("provider_index", [0, 1, 2])
def test_documented_llm_providers_use_the_same_openai_compatible_adapter(
    monkeypatch: pytest.MonkeyPatch,
    provider_index: int,
) -> None:
    from xhs_food.services import llm_service

    expected = _contract()["llm"]
    provider = expected["providers"][provider_index]
    captured: dict = {}

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(adapter="fake")

    monkeypatch.setenv(expected["credential_env"], "fixture-key")
    monkeypatch.setenv(expected["base_url_env"], provider["base_url"])
    monkeypatch.setenv(expected["model_env"], provider["model"])
    monkeypatch.setattr(llm_service, "ChatOpenAI", fake_chat_openai)

    service = llm_service.LLMService()
    service.get_llm()

    assert captured == {
        "model": provider["model"],
        "temperature": 0.2,
        "max_tokens": 1024,
        "api_key": "fixture-key",
        "base_url": provider["base_url"],
    }


def test_llm_model_constructor_argument_has_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    from xhs_food.services.llm_service import LLMService

    monkeypatch.setenv("DEFAULT_LLM_MODEL", "environment-model")
    assert LLMService(model_name="constructor-model")._model_name == "constructor-model"
    assert LLMService()._model_name == "environment-model"
    monkeypatch.delenv("DEFAULT_LLM_MODEL")
    assert LLMService()._model_name == "Qwen/Qwen3-8B"


def test_stdio_node_signer_command_and_environment_without_starting_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xhs_food.auth import signer

    expected = _contract()["node_signer"]
    captured: dict = {}

    class FakeReadable:
        def readline(self):
            return "[signer] ready\n"

        def read(self):
            return ""

        def close(self):
            return None

    class FakeWritable(FakeReadable):
        def write(self, value):
            return len(value)

        def flush(self):
            return None

    class FakeProcess:
        def __init__(self):
            self.stderr = FakeReadable()
            self.stdout = FakeReadable()
            self.stdin = FakeWritable()

        def terminate(self):
            return None

        def wait(self, timeout):
            assert timeout == 3
            return 0

        def kill(self):
            return None

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(signer, "ensure_node_modules", lambda: None)
    monkeypatch.setattr(signer.subprocess, "Popen", fake_popen)
    profile = SimpleNamespace(cookie_str="fixture-cookie", user_agent="fixture-agent")

    client = signer.StdioSignerClient(profile)
    try:
        assert captured["args"] == ["node", str(signer.SIGNER_JS)]
        assert captured["kwargs"]["env"][expected["environment"]["required"]] == "fixture-cookie"
        assert captured["kwargs"]["env"][expected["environment"]["optional"]] == "fixture-agent"
        assert captured["kwargs"]["text"] is True
        assert captured["kwargs"]["bufsize"] == 1
    finally:
        client.close()


def test_missing_node_dependency_runs_npm_install_and_exits_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from xhs_food.auth import node_runtime

    expected = _contract()["node_signer"]
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=1, stderr="fixture npm failure")

    monkeypatch.setattr(node_runtime, "NODE_DIR", tmp_path)
    monkeypatch.setattr(node_runtime, "NODE_MODULES", tmp_path / "node_modules")
    monkeypatch.setattr(node_runtime.subprocess, "run", fake_run)

    with pytest.raises(SystemExit, match="fixture npm failure"):
        node_runtime.ensure_node_modules()

    assert captured["args"] == expected["dependency_behavior"]["missing_action"]
    assert captured["kwargs"]["cwd"] == str(tmp_path)
    assert captured["kwargs"]["capture_output"] is True
    assert captured["kwargs"]["text"] is True


def test_node_signer_manifest_protocol_and_missing_lock_snapshot() -> None:
    expected = _contract()["node_signer"]
    package_path = ROOT / expected["package_manifest"]
    package = json.loads(package_path.read_text(encoding="utf-8"))
    javascript = (ROOT / expected["javascript_source"]).read_text(encoding="utf-8")

    assert package["dependencies"] == {
        expected["dependency_behavior"]["dependency"]: expected["dependency_behavior"]["version"]
    }
    assert (package_path.parent / "package-lock.json").exists() is expected["package_lock_present"]
    assert "process.env.XHS_COOKIE" in javascript
    assert "process.env.XHS_UA" in javascript
    assert 'a.startsWith("--socket=")' in javascript
    assert "fs.chmodSync(socketPath, 0o600)" in javascript
    assert 'buf.indexOf("\\n")' in javascript


def test_dockerfile_entry_port_uid_writable_dirs_and_healthcheck_snapshot() -> None:
    expected = _contract()["deployment"]["dockerfile"]
    text = (ROOT / expected["source"]).read_text(encoding="utf-8")
    instructions = _dockerfile_instructions(text)
    from_lines = [line for line in instructions if line.startswith("FROM ")]
    expose_lines = [line for line in instructions if line.startswith("EXPOSE ")]
    entrypoint_lines = [line for line in instructions if line.startswith("ENTRYPOINT ")]
    cmd_line = next(line for line in instructions if line.startswith("CMD ["))
    health_line = next(line for line in instructions if line.startswith("HEALTHCHECK "))

    assert from_lines == [
        f"FROM {expected['node_image']} AS node-deps",
        f"FROM {expected['builder_image']} AS builder",
        f"FROM {expected['runtime_image']} AS runtime",
    ]
    assert expose_lines == [f"EXPOSE {expected['exposed_port']}"]
    assert entrypoint_lines == []
    assert expected["entrypoint"] is None
    assert json.loads(cmd_line.removeprefix("CMD ")) == expected["cmd"]
    assert f"--uid {expected['uid']} --gid app" in text
    assert f"--gid {expected['gid']} app" in text
    assert f"USER {expected['runtime_user']}" in instructions
    for directory in expected["writable_directories"]:
        assert directory in text
    for value in ("interval", "timeout", "start_period", "retries"):
        option = value.replace("_", "-")
        assert f"--{option}={expected['healthcheck'][value]}" in health_line
    assert expected["healthcheck"]["url"] in health_line
    assert f"timeout={expected['healthcheck']['request_timeout_seconds']}" in health_line
    assert f"status=={expected['healthcheck']['expected_status']}" in health_line


def test_compose_services_overrides_volumes_and_healthchecks_snapshot() -> None:
    expected = _contract()["deployment"]["compose"]
    compose = yaml.safe_load((ROOT / expected["source"]).read_text(encoding="utf-8"))
    services = compose["services"]
    app = services["app"]

    assert sorted(services) == expected["services"]
    assert ("frontend" in services) is expected["frontend_service_present"]
    assert app["env_file"] == expected["app_env_file"]
    assert app["environment"] == expected["app_environment_overrides"]
    assert app["ports"] == [expected["app_port_mapping"]]
    assert app["volumes"] == expected["app_volumes"]
    assert sorted(compose["volumes"]) == expected["named_volumes"]
    assert services["redis"]["image"] == expected["redis_image"]
    assert services["postgres"]["image"] == expected["postgres_image"]
    assert ("EVENT_BUS_BACKEND" in app["environment"]) is expected[
        "event_bus_backend_override_present"
    ]
    assert expected["healthcheck_url"] in " ".join(app["healthcheck"]["test"])


def test_documented_deployment_conflicts_are_frozen_as_current_facts() -> None:
    expected = _contract()["deployment"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert expected["readme"]["python_requirement"] in readme
    assert expected["readme"]["startup_command"] in readme
    docker_checkbox = "- [x] 🐳 Docker 部署支持" in readme
    assert docker_checkbox is expected["readme"]["docker_support_checked"]
    assert "python:3.11-slim" in dockerfile
    assert 'requires-python = ">=3.12,<3.13"' in (ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "npm ci --omit=dev; else npm install --omit=dev" in dockerfile
    assert len(expected["known_conflicts"]) == 5
