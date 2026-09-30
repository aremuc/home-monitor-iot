"""API tests. Imagga is mocked, so no credentials or network are needed."""

import pytest
from fastapi.testclient import TestClient

import server

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(server, "IMAGES_DIR", str(tmp_path / "images"))
    with TestClient(server.app) as c:
        yield c


def upload(client, tags, monkeypatch, name="cam.png", content_type="image/png"):
    monkeypatch.setattr(server, "call_imagga_tags", lambda path: tags)
    return client.post(
        "/api/image", files={"file": (name, PNG_BYTES, content_type)}
    )


def test_upload_stores_image_and_tags(client, monkeypatch):
    resp = upload(client, ["person", "kitchen"], monkeypatch)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tags"] == ["person", "kitchen"]
    assert client.get(f"/api/image/{body['filename']}").status_code == 200


def test_upload_rejects_non_image(client, monkeypatch):
    resp = upload(client, [], monkeypatch, name="x.txt", content_type="text/plain")
    assert resp.status_code == 400


def test_upload_rejects_oversized_file(client, monkeypatch):
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 8)
    resp = upload(client, ["person"], monkeypatch)
    assert resp.status_code == 413


def test_tagging_failure_returns_502_and_leaves_no_file(client, monkeypatch, tmp_path):
    def boom(path):
        raise server.TaggingError("upstream down")

    monkeypatch.setattr(server, "call_imagga_tags", boom)
    resp = client.post("/api/image", files={"file": ("a.png", PNG_BYTES, "image/png")})
    assert resp.status_code == 502
    assert list((tmp_path / "images").iterdir()) == []


def test_tags_and_person_detection_by_range(client, monkeypatch):
    upload(client, ["person", "room"], monkeypatch)
    rng = {"from": "2000-01-01T00:00:00", "to": "2100-01-01T00:00:00"}

    assert set(client.get("/api/tags", params=rng).json()["tags"]) == {"person", "room"}
    assert client.get("/api/personDetected", params=rng).json()["personDetected"] is True

    past = {"from": "2000-01-01T00:00:00", "to": "2000-01-02T00:00:00"}
    assert client.get("/api/personDetected", params=past).json()["personDetected"] is False


def test_invalid_or_reversed_range_is_400(client):
    assert client.get("/api/tags", params={"from": "nope", "to": "2025-01-01"}).status_code == 400
    reversed_range = {"from": "2025-02-01T00:00:00", "to": "2025-01-01T00:00:00"}
    assert client.get("/api/tags", params=reversed_range).status_code == 400


def test_popular_tags_orders_by_count(client, monkeypatch):
    upload(client, ["cat", "sofa"], monkeypatch)
    upload(client, ["cat"], monkeypatch)
    top = client.get("/api/popularTags").json()
    assert top[0] == {"tag": "cat", "count": 2}
