"""Multi-region / DR artifacts (issue #71 / G6)."""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_BASE = Path(__file__).resolve().parents[1]
RESIDENCY = REPO_BASE / "config" / "residency.yaml"
DR = REPO_BASE / "config" / "dr.yaml"
TERRAFORM = REPO_BASE / "deployment" / "terraform"
DR_RUNBOOK = REPO_BASE / "docs" / "dr-runbook.md"


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_residency_config_exists() -> None:
    cfg = _load_yaml(RESIDENCY)
    assert cfg["enabled"] is False
    assert "default_region" in cfg
    assert "routing" in cfg
    assert "failover" in cfg
    assert "disaster_recovery" in cfg


def test_dr_config_exists() -> None:
    cfg = _load_yaml(DR)
    assert cfg["enabled"] is False
    assert cfg["rpo_minutes"] > 0
    assert cfg["rto_minutes"] > 0
    assert cfg["backup"]["store"] is True
    assert cfg["restore"]["runbook_path"] == "docs/dr-runbook.md"


def test_cloud_terraform_modules_exist() -> None:
    for cloud in ("aws", "azure", "gcp"):
        assert (TERRAFORM / "modules" / cloud / "main.tf").is_file()


def test_multi_region_environment_exists() -> None:
    assert (TERRAFORM / "environments" / "multi-region" / "main.tf").is_file()


def test_dr_runbook_exists() -> None:
    text = DR_RUNBOOK.read_text(encoding="utf-8")
    assert "RPO" in text and "RTO" in text
    assert "backup" in text.lower()
    assert "restore" in text.lower()
    assert "failover" in text.lower()
    assert "BaseStore" in text


def test_residency_routing_documented() -> None:
    cfg = _load_yaml(RESIDENCY)
    assert cfg["routing"]["strategy"] in ("header", "geo", "tenant")
    assert "allowed_regions" in cfg["routing"]
