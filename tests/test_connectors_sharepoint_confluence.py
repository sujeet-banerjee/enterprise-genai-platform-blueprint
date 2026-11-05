"""SharePoint/Confluence connector tests (#116)."""

from __future__ import annotations

from core.implementations.connectors import ConfluenceConnector, SharePointConnector
from core.interfaces.connector import SyncCursor
from core.registry.connector_registry import ConnectorRegistry


def test_sharepoint_validate_and_discover():
    c = SharePointConnector(site_url="https://contoso.sharepoint.com/sites/x", library="Docs")
    c.validate()
    assert c.discover()[0]["site_url"].startswith("https://")


def test_sharepoint_fetch_items_and_acl():
    c = SharePointConnector(site_url="https://s", config={"items": [{"id": "1", "content": "hi", "acl": {"allowed_tenants": ["t1"]}}]})
    docs, _ = c.sync()
    assert docs[0].metadata["allowed_tenants"] == ["t1"]
    assert docs[0].metadata["source"] == "sharepoint"


def test_confluence_validate_and_discover():
    c = ConfluenceConnector(base_url="https://confluence.example.com", space="ENG")
    c.validate()
    assert c.discover()[0]["space"] == "ENG"


def test_confluence_fetch_items_and_acl():
    c = ConfluenceConnector(base_url="https://c", config={"items": [{"id": "p1", "body": "page", "acl": {"allowed_groups": ["g1"]}}]})
    docs, _ = c.sync()
    assert docs[0].content == "page"
    assert docs[0].metadata["allowed_groups"] == ["g1"]


def test_registry_creates_sharepoint_and_confluence(tmp_path):
    cfg = tmp_path / "ingestion.yaml"
    cfg.write_text(
        """
enabled: true
connectors:
  sp:
    type: sharepoint
    site_url: https://s
  cf:
    type: confluence
    base_url: https://c
""",
        encoding="utf-8",
    )
    r = ConnectorRegistry(config_path=str(cfg))
    assert r.create("sp").source_type == "sharepoint"
    assert r.create("cf").source_type == "confluence"


def test_sharepoint_confluence_client_hooks():
    class SPClient:
        def list_items(self, **kw):
            return [{"id": "x", "content": "c"}]

    class CFClient:
        def list_pages(self, **kw):
            return [{"id": "y", "body": "b"}]

    sp = SharePointConnector(site_url="https://s", client=SPClient())
    cf = ConfluenceConnector(base_url="https://c", client=CFClient())
    assert list(sp.fetch())[0].content == "c"
    assert list(cf.fetch(SyncCursor(value=None)))[0].content == "b"
