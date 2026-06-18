from types import SimpleNamespace

from click.testing import CliRunner

from codepilot.doctor import DoctorItem, DoctorReport, render_report


def test_doctor_report_exit_code_reflects_failures():
    ok_report = DoctorReport(items=[DoctorItem("OK", "Python", "3.11")])
    fail_report = DoctorReport(items=[DoctorItem("FAIL", "API key", "missing")])

    assert ok_report.has_failures() is False
    assert ok_report.exit_code() == 0
    assert fail_report.has_failures() is True
    assert fail_report.exit_code() == 1


def test_render_report_includes_header_and_items():
    report = DoctorReport(items=[
        DoctorItem("OK", "Python", "3.11"),
        DoctorItem("WARN", "MCP SDK", "optional dependency not installed"),
        DoctorItem("FAIL", "API key", "CODEPILOT_ARC_API_KEY missing"),
    ])

    output = render_report(report)

    assert output.startswith("CodePilot Doctor")
    assert "[OK] Python: 3.11" in output
    assert "[WARN] MCP SDK: optional dependency not installed" in output
    assert "[FAIL] API key: CODEPILOT_ARC_API_KEY missing" in output


def test_provider_env_var_uses_uppercase_provider_name():
    from codepilot.doctor import _provider_env_var

    assert _provider_env_var("arc") == "CODEPILOT_ARC_API_KEY"
    assert _provider_env_var("deepseek") == "CODEPILOT_DEEPSEEK_API_KEY"


def test_has_provider_api_key_accepts_config_or_environment():
    from codepilot.doctor import _has_provider_api_key

    assert _has_provider_api_key("arc", "config-secret", {}) is True
    assert _has_provider_api_key("arc", "", {"CODEPILOT_ARC_API_KEY": "env-secret"}) is True
    assert _has_provider_api_key("arc", None, {"CODEPILOT_ARC_API_KEY": "env-secret"}) is True
    assert _has_provider_api_key("arc", "", {}) is False


def test_render_report_does_not_include_api_key_values():
    report = DoctorReport(items=[DoctorItem("OK", "API key", "CODEPILOT_ARC_API_KEY found")])
    output = render_report(report)

    assert "config-secret" not in output
    assert "env-secret" not in output


def test_run_doctor_reports_missing_api_key(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    config = SimpleNamespace(
        default=SimpleNamespace(provider="arc", model="glm-5.1"),
        providers={"arc": SimpleNamespace(api_key="", models=["glm-5.1"])},
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text("providers: {}\n")
    monkeypatch.setattr(doctor, "load_config", lambda: config)
    monkeypatch.setattr(doctor, "CONFIG_FILE", config_file)
    monkeypatch.delenv("CODEPILOT_ARC_API_KEY", raising=False)

    report = doctor.run_doctor(working_dir=tmp_path)

    assert report.exit_code() == 1
    assert any(item.severity == "FAIL" and item.label == "API key" for item in report.items)


def test_run_doctor_accepts_environment_api_key(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    config = SimpleNamespace(
        default=SimpleNamespace(provider="arc", model="glm-5.1"),
        providers={"arc": SimpleNamespace(api_key="", models=["glm-5.1"])},
    )
    config_file = tmp_path / "config.yaml"
    config_file.write_text("providers: {}\n")
    monkeypatch.setattr(doctor, "load_config", lambda: config)
    monkeypatch.setattr(doctor, "CONFIG_FILE", config_file)
    monkeypatch.setenv("CODEPILOT_ARC_API_KEY", "super-secret-value")

    report = doctor.run_doctor(working_dir=tmp_path)
    output = doctor.render_report(report)

    assert any(item.severity == "OK" and item.label == "API key" for item in report.items)
    assert "super-secret-value" not in output


def test_run_doctor_reports_config_load_failure(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    def fail_load_config():
        raise RuntimeError("bad config")

    monkeypatch.setattr(doctor, "load_config", fail_load_config)

    report = doctor.run_doctor(working_dir=tmp_path)

    assert report.exit_code() == 1
    assert any(item.severity == "FAIL" and item.label == "Config" for item in report.items)


def test_run_doctor_does_not_load_or_create_missing_config(monkeypatch, tmp_path):
    import codepilot.doctor as doctor

    missing_config = tmp_path / "config.yaml"

    called = {"load_config": False}

    def fail_load_config():
        called["load_config"] = True
        raise AssertionError("load_config should not be called when config file is missing")

    monkeypatch.setattr(doctor, "CONFIG_FILE", missing_config)
    monkeypatch.setattr(doctor, "load_config", fail_load_config)

    report = doctor.run_doctor(working_dir=tmp_path)

    assert called["load_config"] is False

    assert missing_config.exists() is False
    assert any(item.severity == "WARN" and item.label == "Config file" for item in report.items)
    assert any(item.severity == "FAIL" and item.label == "Config" for item in report.items)


def test_cli_doctor_prints_report_and_uses_exit_code(monkeypatch):
    import codepilot.cli as cli
    from codepilot.cli import main

    def fake_run_doctor():
        return DoctorReport(items=[DoctorItem("FAIL", "API key", "CODEPILOT_ARC_API_KEY missing")])

    monkeypatch.setattr(cli, "run_doctor", fake_run_doctor)
    monkeypatch.setattr(cli, "render_report", lambda report: "CodePilot Doctor\n\n[FAIL] API key: missing")

    result = CliRunner().invoke(main, ["--doctor"])

    assert result.exit_code == 1
    assert "CodePilot Doctor" in result.output
    assert "API key" in result.output


def test_cli_doctor_does_not_initialize_provider_registry(monkeypatch):
    import codepilot.cli as cli
    from codepilot.cli import main

    monkeypatch.setattr(cli, "run_doctor", lambda: DoctorReport(items=[]))
    monkeypatch.setattr(cli, "render_report", lambda report: "CodePilot Doctor")

    def fail_load_config():
        raise AssertionError("load_config should not be called before doctor exits")

    monkeypatch.setattr("codepilot.config.settings.load_config", fail_load_config)

    result = CliRunner().invoke(main, ["--doctor"])

    assert result.exit_code == 0
    assert "CodePilot Doctor" in result.output


def test_cli_doctor_does_not_set_working_dir_environment(monkeypatch):
    import codepilot.cli as cli
    from codepilot.cli import main

    monkeypatch.delenv("CODEPILOT_WORKING_DIR", raising=False)
    monkeypatch.setattr(cli, "run_doctor", lambda: DoctorReport(items=[]))
    monkeypatch.setattr(cli, "render_report", lambda report: "CodePilot Doctor")

    result = CliRunner().invoke(main, ["--doctor"])

    assert result.exit_code == 0
    assert "CODEPILOT_WORKING_DIR" not in __import__("os").environ
