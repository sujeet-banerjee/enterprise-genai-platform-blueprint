"""Structural and schema guards for CI supply-chain gates (issue #225)."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from app.supply_chain import WaiverError, ignores, load_waivers, main, write_ignores

REPO = Path(__file__).resolve().parents[1]
CI = REPO / ".github" / "workflows" / "ci.yml"
DEPENDABOT = REPO / ".github" / "dependabot.yml"
WAIVERS = REPO / "security" / "waivers.yml"
SECURITY_DOC = REPO / "docs" / "security" / "README.md"
LIFECYCLE_DOC = REPO / "docs" / "engineering-lifecycle.md"
TRIVY_SHA = "a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8"
UPLOAD_SHA = "cf430e030ddbb5b0abf93d22962f4752f3646cd9"
REQUIRED_CONTEXTS = [
    "Lint (ruff)",
    "Type check (mypy)",
    "Tests (Python 3.11)",
    "Tests (Python 3.13)",
    "CodeQL",
    "SCA (pip-audit)",
    "Image scan (Trivy)",
]


def _ci_jobs() -> dict:
    data = yaml.safe_load(CI.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    jobs = data["jobs"]
    assert isinstance(jobs, dict)
    return jobs


def _base_waiver() -> dict:
    return {
        "id": "GHSA-abcd-efgh-ijkl",
        "package": "example==1.0.0",
        "reason": "Documented temporary exception for a transitive path with no exposure.",
        "expires": (date.today() + timedelta(days=30)).isoformat(),
        "owner": "bot-uni",
        "approved_by": "maintainer",
    }


def _write_waivers(path: Path, entries: list[dict]) -> None:
    path.write_text(yaml.safe_dump({"version": 1, "waivers": entries}), encoding="utf-8")


def test_shipped_waiver_file_is_valid_and_bounded() -> None:
    waivers = load_waivers(WAIVERS, today=date(2026, 1, 1))
    assert [waiver.id for waiver in waivers] == [
        "CVE-2025-47273",
        "CVE-2026-23949",
        "CVE-2026-24049",
    ]
    assert all(waiver.expires == date(2027, 2, 15) for waiver in waivers)
    assert ignores(waivers, "pip-audit") == [waiver.id for waiver in waivers]
    assert ignores(waivers, "trivy") == [waiver.id for waiver in waivers]


def test_valid_waivers_are_parsed_and_sorted(tmp_path: Path) -> None:
    later = _base_waiver()
    earlier = _base_waiver()
    earlier["id"] = "CVE-2030-1234"
    _write_waivers(tmp_path / "waivers.yml", [later, earlier])
    waivers = load_waivers(tmp_path / "waivers.yml")
    assert [waiver.id for waiver in waivers] == ["CVE-2030-1234", "GHSA-abcd-efgh-ijkl"]
    assert waivers[0].owner == "bot-uni"
    assert waivers[0].expires == date.fromisoformat(earlier["expires"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("id", "not-an-advisory"),
        ("reason", "too short"),
        ("expires", "not-a-date"),
        ("owner", ""),
        ("approved_by", ""),
    ],
)
def test_invalid_waiver_fields_fail_closed(tmp_path: Path, field: str, value: object) -> None:
    entry = _base_waiver()
    entry[field] = value
    path = tmp_path / "waivers.yml"
    _write_waivers(path, [entry])
    with pytest.raises(WaiverError):
        load_waivers(path)


def test_missing_and_unknown_fields_fail_closed(tmp_path: Path) -> None:
    missing = _base_waiver()
    missing.pop("package")
    path = tmp_path / "waivers.yml"
    _write_waivers(path, [missing])
    with pytest.raises(WaiverError, match="missing fields"):
        load_waivers(path)
    extra = _base_waiver()
    extra["severity"] = "LOW"
    _write_waivers(path, [extra])
    with pytest.raises(WaiverError, match="unknown fields"):
        load_waivers(path)


def test_expired_and_duplicate_waivers_fail_closed(tmp_path: Path) -> None:
    expired = _base_waiver()
    expired["expires"] = (date.today() - timedelta(days=1)).isoformat()
    path = tmp_path / "waivers.yml"
    _write_waivers(path, [expired])
    with pytest.raises(WaiverError, match="expired"):
        load_waivers(path)
    duplicate = _base_waiver()
    _write_waivers(path, [duplicate, deepcopy(duplicate)])
    with pytest.raises(WaiverError, match="duplicate"):
        load_waivers(path)


def test_ignore_formats_are_supported_and_strict(tmp_path: Path) -> None:
    entry = _base_waiver()
    path = tmp_path / "waivers.yml"
    _write_waivers(path, [entry])
    waivers = load_waivers(path)
    assert ignores(waivers, "pip-audit") == [entry["id"]]
    assert ignores(waivers, "trivy") == [entry["id"]]
    with pytest.raises(WaiverError, match="unsupported ignore format"):
        ignores(waivers, "sarif")
    out = tmp_path / "ignore.txt"
    write_ignores(waivers, "trivy", out)
    assert out.read_text(encoding="utf-8") == f"{entry['id']}\n"


def test_cli_writes_ignore_files_and_reports_invalid_input(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    entry = _base_waiver()
    waivers_path = tmp_path / "waivers.yml"
    _write_waivers(waivers_path, [entry])
    out = tmp_path / "pip-ignore.txt"
    assert main(
        ["ignores", "--waivers", str(waivers_path), "--format", "pip-audit", "--output", str(out)]
    ) == 0
    assert out.read_text(encoding="utf-8") == f"{entry['id']}\n"
    assert capsys.readouterr().out == ""
    assert main(["ignores", "--waivers", str(waivers_path), "--format", "trivy"]) == 0
    assert capsys.readouterr().out == f"{entry['id']}\n"
    assert main(["ignores", "--waivers", str(tmp_path / "missing.yml")]) == 2
    assert "FAIL" in capsys.readouterr().err


def test_ci_contains_required_sca_job() -> None:
    jobs = _ci_jobs()
    job = jobs["supply-chain-sca"]
    assert job["name"] == "SCA (pip-audit)"
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "pip-audit==2.10.1" in commands
    assert "python -m app.supply_chain ignores --format pip-audit" in commands
    assert "pip-audit --format json" in commands
    for requirement in (
        "requirements.txt",
        "requirements-dev.txt",
        "requirements-observability.txt",
        "requirements-ui.txt",
    ):
        assert f"--requirement {requirement}" in commands


def test_ci_contains_required_trivy_job_with_pinned_action() -> None:
    jobs = _ci_jobs()
    job = jobs["image-scan"]
    assert job["name"] == "Image scan (Trivy)"
    commands = "\n".join(str(step.get("run", "")) for step in job["steps"])
    assert "python -m app.supply_chain ignores --format trivy" in commands
    assert "docker build -f deployment/Dockerfile" in commands
    scan_step = next(step for step in job["steps"] if "trivy-action@" in str(step.get("uses")))
    assert scan_step["uses"] == f"aquasecurity/trivy-action@{TRIVY_SHA}"
    config = scan_step["with"]
    assert config["severity"] == "CRITICAL,HIGH"
    assert config["ignore-unfixed"] is True
    assert config["exit-code"] == "1"
    assert config["trivyignores"] == ".trivyignore"
    assert config["format"] == "json"


def test_ci_uploads_both_scanner_reports() -> None:
    jobs = _ci_jobs()
    uploads = {}
    for key in ("supply-chain-sca", "image-scan"):
        for step in jobs[key]["steps"]:
            if str(step.get("uses", "")).startswith("actions/upload-artifact@"):
                assert step["uses"] == f"actions/upload-artifact@{UPLOAD_SHA}"
                uploads[key] = step["with"]["name"]
    assert uploads == {"supply-chain-sca": "pip-audit-report", "image-scan": "trivy-report"}


def test_required_contexts_match_lifecycle_and_ci_names() -> None:
    jobs = _ci_jobs()
    ci_names = {job["name"] for job in jobs.values()}
    lifecycle = LIFECYCLE_DOC.read_text(encoding="utf-8")
    section = lifecycle.split("These seven status checks are **required**")[1].split(
        "These jobs run on the PR"
    )[0]
    documented = [line.split("|")[1].strip().strip("`") for line in section.splitlines() if line.startswith("| `")]
    assert documented == REQUIRED_CONTEXTS
    for context in REQUIRED_CONTEXTS:
        if context == "CodeQL":
            continue
        if context.startswith("Tests (Python"):
            assert "Tests (Python ${{ matrix.python-version }})" in ci_names
            continue
        assert context in ci_names
    assert "`CodeQL` / `Analyze" not in lifecycle


def test_dependabot_is_weekly_bounded_and_grouped() -> None:
    config = yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))
    assert config["version"] == 2
    ecosystems = {entry["package-ecosystem"] for entry in config["updates"]}
    assert ecosystems == {"pip", "github-actions"}
    for entry in config["updates"]:
        assert entry["schedule"]["interval"] == "weekly"
        assert entry["schedule"]["day"] == "monday"
        assert 0 < entry["open-pull-requests-limit"] <= 10
        assert entry["groups"]
        assert entry["commit-message"]["prefix"] == "deps"


def test_security_docs_match_scanner_state_and_waiver_policy() -> None:
    security = SECURITY_DOC.read_text(encoding="utf-8")
    for expected in (
        "F-05",
        "**Fixed** (#225)",
        "CodeQL",
        "SCA (pip-audit)",
        "Image scan (Trivy)",
        "security/waivers.yml",
        "expired waivers fail the gate",
        "no tokens or secrets",
        "waived until `2027-02-15`",
        "non-provider patterns and validity checks remain disabled",
        "**Not performed**",
    ):
        assert expected in security
    assert "Not run** (#225)" not in security


def test_scanner_config_contains_no_secret_references() -> None:
    jobs = _ci_jobs()
    scanner_jobs = yaml.safe_dump(
        {key: jobs[key] for key in ("supply-chain-sca", "image-scan")}
    )
    for needle in ("secrets.", "OPENAI_API_KEY", "HF_TOKEN", "api_key", "password", "token"):
        assert needle not in scanner_jobs


def test_dockerfile_addresses_image_scan_findings_without_waivers() -> None:
    dockerfile = (REPO / "deployment" / "Dockerfile").read_text(encoding="utf-8")
    assert "apt-get upgrade -y --no-install-recommends" in dockerfile
    for pin in ("setuptools==78.1.1", "wheel==0.46.2", "jaraco.context==6.1.0"):
        assert pin in dockerfile


def test_waiver_file_contains_only_documented_expiring_entries() -> None:
    config = yaml.safe_load(WAIVERS.read_text(encoding="utf-8"))
    assert config["version"] == 1
    assert len(config["waivers"]) == 3
    assert all(entry["expires"] == "2027-02-15" for entry in config["waivers"])
    assert {entry["id"] for entry in config["waivers"]} == {
        "CVE-2025-47273",
        "CVE-2026-23949",
        "CVE-2026-24049",
    }
