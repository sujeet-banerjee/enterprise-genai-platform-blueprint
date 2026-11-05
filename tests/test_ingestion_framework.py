"""Ingestion framework tests for #115."""

from __future__ import annotations

import json
from pathlib import Path

from core.config.schema import SCHEMAS
from core.config.validator import validate_config_data
from core.interfaces.connector import BaseConnector, RawItem, SyncCursor
from core.registry.connector_registry import ConnectorRegistry
from core.services.acl import normalize_document
from core.services.ingestion_service import IngestionService


class DummyConnector(BaseConnector):
    def __init__(self, name: str = "dummy", config: dict | None = None):
        super().__init__(name=name, source_type="dummy", config=config)

    def validate(self) -> None:
        return None

    def discover(self) -> list:
        return [{"id": "x"}]

    def fetch(self, cursor: SyncCursor | None = None):
        return [RawItem(id="1", content="hello", metadata={"x": 1}, acl={"allowed_tenants": ["t1"]})]


def test_base_connector_to_documents_preserves_acl_and_source(tmp_path):
    c = DummyConnector()
    docs = c.to_documents([RawItem(id="1", content="hi", metadata={"k": "v"}, acl={"allowed_tenants": ["a"]})])
    assert docs[0].metadata["source"] == "dummy"
    assert docs[0].metadata["connector"] == "dummy"
    assert docs[0].metadata["source_id"] == "1"
    assert docs[0].metadata["allowed_tenants"] == ["a"]
    nd = normalize_document(docs[0])
    assert "allowed_tenants" in nd.metadata


def test_connector_registry_default_off():
    r = ConnectorRegistry()
    assert r.describe()["enabled"] is False
    assert r.create() is None


def test_connector_registry_filesystem_and_sync(tmp_path):
    data = [{"content": "doc1"}, {"content": "doc2", "metadata": {"k": 1}}]
    p = tmp_path / "docs.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    cfg = tmp_path / "ingestion.yaml"
    cfg.write_text(
        """
enabled: true
default_connector: local
connectors:
  local:
    type: filesystem
    path: %s
""" % str(p).replace("\\", "/"),
        encoding="utf-8",
    )
    r = ConnectorRegistry(config_path=str(cfg))
    c = r.create()
    assert c is not None
    c.validate()
    docs, cur = c.sync()
    assert len(docs) == 2
    assert docs[0].metadata["source"] == "filesystem"


def test_ingestion_service_incremental_state(tmp_path):
    data = [{"content": "hello"}]
    p = tmp_path / "docs.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    cfg = tmp_path / "ingestion.yaml"
    cfg.write_text(
        """
enabled: true
default_connector: local
state_path: %s
connectors:
  local:
    type: filesystem
    path: %s
""" % (str(tmp_path / "state.json").replace("\\", "/"), str(p).replace("\\", "/")),
        encoding="utf-8",
    )
    svc = IngestionService(config_path=str(cfg))
    res = svc.sync()
    assert res["enabled"] is True
    assert res["count"] == 1
    st = Path(tmp_path / "state.json")
    assert st.exists()


def test_ingestion_schema_validates():
    assert "ingestion" in SCHEMAS
    data = {"enabled": True, "connectors": {"x": {"type": "filesystem"}}}
    issues = validate_config_data(data, "ingestion")
    assert isinstance(issues, list)
    assert issues == []


def test_connector_registry_register_custom():
    r = ConnectorRegistry()
    def _factory(name="custom", **kw):
        return DummyConnector(name=name)
    r.register("custom", _factory)
    assert "custom" in r.list_providers()
