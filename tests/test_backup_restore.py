"""Backup/restore automation + verification tests (#119)."""

from core.services.backup_restore import export_store, restore_store, verify_backup
from core.services.store_backends import MemoryStore


def test_export_and_verify(tmp_path):
    s = MemoryStore()
    s.set("a:1", {"key": "a:1", "v": 1})
    s.set("b:1", {"key": "b:1", "v": 2})
    out = tmp_path / "backup.json"
    m = export_store(s, out)
    assert m["count"] == 2
    ok, meta = verify_backup(out)
    assert ok is True
    assert meta["count"] == 2


def test_verify_detects_tamper(tmp_path):
    s = MemoryStore()
    s.set("k", {"key": "k", "v": 1})
    out = tmp_path / "backup.json"
    export_store(s, out)
    txt = out.read_text()
    out.write_text(txt.replace('"v": 1', '"v": 9'))
    ok, meta = verify_backup(out)
    assert ok is False
    assert meta["expected"] != meta["actual"]


def test_restore_roundtrip(tmp_path):
    s1 = MemoryStore()
    s1.set("k1", {"key": "k1", "v": 1})
    s1.set("k2", {"key": "k2", "v": 2})
    out = tmp_path / "backup.json"
    export_store(s1, out)
    s2 = MemoryStore()
    res = restore_store(s2, out)
    assert res["ok"] is True
    assert res["restored"] == 2
    assert s2.get("k1")["v"] == 1


def test_restore_with_clear(tmp_path):
    s1 = MemoryStore()
    s1.set("k1", {"key": "k1", "v": 1})
    out = tmp_path / "backup.json"
    export_store(s1, out)
    s2 = MemoryStore()
    s2.set("old", {"key": "old", "v": 9})
    res = restore_store(s2, out, clear=True)
    assert res["restored"] == 1
    assert s2.get("old") is None


def test_restore_rejects_bad_checksum(tmp_path):
    s = MemoryStore()
    s.set("k", {"key": "k", "v": 1})
    out = tmp_path / "backup.json"
    export_store(s, out)
    txt = out.read_text()
    out.write_text(txt.replace('"v": 1', '"v": 9'))
    s2 = MemoryStore()
    res = restore_store(s2, out)
    assert res["ok"] is False
    assert res["restored"] == 0


def test_restore_can_skip_verify(tmp_path):
    s = MemoryStore()
    s.set("k", {"key": "k", "v": 1})
    out = tmp_path / "backup.json"
    export_store(s, out)
    txt = out.read_text()
    out.write_text(txt.replace('"v": 1', '"v": 9'))
    s2 = MemoryStore()
    res = restore_store(s2, out, verify=False)
    assert res["ok"] is True
    assert res["restored"] == 1
