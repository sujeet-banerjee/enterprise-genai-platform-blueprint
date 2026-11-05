"""Object storage connector tests (#117)."""

from core.implementations.connectors import AzureBlobConnector, GCSConnector, S3Connector
from core.registry.connector_registry import ConnectorRegistry


def test_s3_validate_discover_fetch_acl():
    c = S3Connector(bucket="b", prefix="p/", config={"items": [{"key": "k1", "content": "hi", "acl": {"allowed_tenants": ["t1"]}}]})
    c.validate()
    assert c.discover()[0]["bucket"] == "b"
    docs, _ = c.sync()
    assert docs[0].metadata["source"] == "s3"
    assert docs[0].metadata["allowed_tenants"] == ["t1"]


def test_azure_blob_validate_discover_fetch_acl():
    c = AzureBlobConnector(container="c1", config={"items": [{"name": "n1", "body": "hi", "acl": {"allowed_groups": ["g1"]}}]})
    c.validate()
    assert c.discover()[0]["container"] == "c1"
    docs, _ = c.sync()
    assert docs[0].metadata["source"] == "azure_blob"
    assert docs[0].metadata["allowed_groups"] == ["g1"]


def test_gcs_validate_discover_fetch_acl():
    c = GCSConnector(bucket="b", config={"items": [{"name": "o1", "body": "hi", "acl": {"allowed_users": ["u1"]}}]})
    c.validate()
    assert c.discover()[0]["bucket"] == "b"
    docs, _ = c.sync()
    assert docs[0].metadata["source"] == "gcs"
    assert docs[0].metadata["allowed_users"] == ["u1"]


def test_registry_creates_object_connectors(tmp_path):
    cfg = tmp_path / "ingestion.yaml"
    cfg.write_text(
        """
enabled: true
connectors:
  s3c:
    type: s3
    bucket: b
  az:
    type: azure_blob
    container: c
  gc:
    type: gcs
    bucket: b2
""",
        encoding="utf-8",
    )
    r = ConnectorRegistry(config_path=str(cfg))
    assert r.create("s3c").source_type == "s3"
    assert r.create("az").source_type == "azure_blob"
    assert r.create("gc").source_type == "gcs"


def test_object_client_hooks():
    class C:
        def list_objects(self, **kw):
            return [{"key": "k", "content": "c"}]

        def list_blobs(self, **kw):
            return [{"name": "n", "content": "b"}]

    assert list(S3Connector(bucket="b", client=C()).fetch())[0].id == "k"
    assert list(AzureBlobConnector(container="c", client=C()).fetch())[0].id == "n"
    # GCS client hook returns via list_objects in this stub, but connector checks list_objects; provide name
    class GC:
        def list_objects(self, **kw):
            return [{"name": "k", "content": "c"}]

    assert list(GCSConnector(bucket="b", client=GC()).fetch())[0].id == "k"


def test_object_validation_errors():
    for cls, kwargs in [(S3Connector, {}), (AzureBlobConnector, {}), (GCSConnector, {})]:
        try:
            cls(**kwargs).validate()
        except ValueError:
            pass
        else:
            raise AssertionError("expected ValueError")
