"""Cross-region persistence strategy tests (#118)."""

from core.services.base_store import build_store
from core.services.store_backends import MemoryStore, RegionalStore


def test_regional_store_namespaces_and_health():
    inner = MemoryStore()
    s = RegionalStore(inner, region="us-east-1", replication={"mode": "async"})
    s.set("k1", {"v": 1})
    assert s.get("k1")["v"] == 1
    assert inner.get("us-east-1:k1") is not None
    h = s.health()
    assert h["region"] == "us-east-1"
    assert h["replication"]["mode"] == "async"


def test_regional_list_prefix():
    s = RegionalStore(MemoryStore(), region="eu-west-1")
    s.set("a:1", {"x": 1})
    s.set("b:1", {"x": 2})
    assert len(s.list(prefix="a:")) == 1
    assert len(s.list()) == 2


def test_build_store_wraps_with_region():
    s = build_store(backend="memory", region="ap-south-1")
    s.set("k", {"v": 1})
    assert s.health()["region"] == "ap-south-1"
    assert s.get("k")["v"] == 1


def test_build_store_no_region_default():
    s = build_store(backend="memory")
    s.set("k", {"v": 1})
    assert "region" not in s.health()


def test_regional_delete_and_clear():
    s = RegionalStore(MemoryStore(), region="r1")
    s.set("k", {"v": 1})
    assert s.delete("k") is True
    s.set("k2", {"v": 2})
    s.clear()
    assert s.list() == []


def test_regional_preserves_region_in_value():
    inner = MemoryStore()
    s = RegionalStore(inner, region="r2")
    s.set("k", {"a": 1})
    stored = inner.get("r2:k")
    assert stored["_region"] == "r2"
