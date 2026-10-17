import httpx
import pytest
from fastapi.testclient import TestClient

from studio import app as studio_app
from studio import models, presets
from studio.fal import FalClient


def test_text_request_keeps_only_supported_options():
    endpoint, p = models.build_request(
        "seedance-1-pro", "a fox", resolution="1080p", duration="5",
        aspect_ratio="9:16", seed="7", camera_fixed=True, generate_audio=True)
    assert endpoint == "fal-ai/bytedance/seedance/v1/pro/text-to-video"
    assert p == {"prompt": "a fox", "resolution": "1080p", "duration": "5",
                 "aspect_ratio": "9:16", "seed": 7, "camera_fixed": True}


def test_image_request_drops_ratio_and_uses_image_endpoint():
    endpoint, p = models.build_request(
        "seedance-2.0", "wave", image_url="data:x", end_image_url="data:y",
        aspect_ratio="16:9", generate_audio=False)
    assert endpoint == "bytedance/seedance-2.0/image-to-video"
    assert "aspect_ratio" not in p and "end_image_url" not in p
    assert p["image_url"] == "data:x" and p["generate_audio"] is False


@pytest.mark.parametrize("kw", [dict(resolution="1080p"), dict(duration="99")])
def test_rejects_options_a_model_lacks(kw):
    with pytest.raises(ValueError):
        models.build_request("seedance-1-lite", "x", **kw)


def test_rejects_empty_prompt_and_unknown_model():
    with pytest.raises(ValueError):
        models.build_request("seedance-2.0", "  ")
    with pytest.raises(ValueError):
        models.build_request("sora", "x")


def test_presets_append_text():
    assert presets.apply("a fox ", "orbit", "none") == \
        "a fox The camera orbits 180 degrees around the subject."


class FakeFal:
    """Plays fal.ai's queue: one status check queued, then done."""

    def __init__(self):
        self.submitted, self.checks = [], 0

    def __call__(self, req):
        assert req.headers.get("authorization") == "Key test" or req.url.host == "cdn.test"
        if req.method == "POST":
            self.submitted.append((req.url.path, req.read()))
            return httpx.Response(200, json={
                "request_id": "r1", "status_url": "https://queue.fal.run/x/requests/r1/status",
                "response_url": "https://queue.fal.run/x/requests/r1"})
        if req.url.path.endswith("/status"):
            self.checks += 1
            return httpx.Response(200, json={"status": "IN_QUEUE", "queue_position": 2}
                                  if self.checks == 1 else {"status": "COMPLETED"})
        if req.url.host == "cdn.test":
            return httpx.Response(200, content=b"MP4DATA")
        return httpx.Response(200, json={"video": {"url": "https://cdn.test/v.mp4"}, "seed": 42})


@pytest.fixture
def client(tmp_path, monkeypatch):
    fake = FakeFal()
    monkeypatch.setattr(studio_app, "fal", FalClient(key="test", transport=httpx.MockTransport(fake)))
    monkeypatch.setattr(studio_app, "OUT", tmp_path / "outputs")
    monkeypatch.setattr(studio_app, "JOBS", tmp_path / "jobs.json")
    return TestClient(studio_app.app), fake


def test_full_flow_text_to_video(client):
    c, fake = client
    r = c.post("/api/generate", data={"model": "seedance-2.0-fast", "prompt": "a fox",
                                      "camera": "dolly-in", "resolution": "720p", "duration": "5"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert fake.submitted[0][0] == "/bytedance/seedance-2.0/fast/text-to-video"
    assert b"Slow dolly in" in fake.submitted[0][1]

    assert c.get(f"/api/jobs/{job['id']}").json()["status"] == "IN_QUEUE"
    done = c.get(f"/api/jobs/{job['id']}").json()
    assert done["status"] == "COMPLETED" and done["seed_used"] == 42
    assert c.get(f"/videos/{done['file']}").content == b"MP4DATA"
    assert [j["id"] for j in c.get("/api/jobs").json()] == [job["id"]]

    assert c.delete(f"/api/jobs/{job['id']}").json() == {"deleted": True}
    assert c.get(f"/videos/{done['file']}").status_code == 404


def test_image_upload_is_sent_as_data_uri(client):
    c, fake = client
    r = c.post("/api/generate", data={"model": "seedance-1-lite", "prompt": "move"},
               files={"image": ("a.png", b"\x89PNG", "image/png")})
    assert r.status_code == 200, r.text
    assert fake.submitted[0][0].endswith("/v1/lite/image-to-video")
    assert b"data:image/png;base64," in fake.submitted[0][1]


def test_bad_option_is_a_400_and_nothing_is_submitted(client):
    c, fake = client
    r = c.post("/api/generate", data={"model": "seedance-1-lite", "prompt": "x", "resolution": "1080p"})
    assert r.status_code == 400 and not fake.submitted


def test_missing_key_is_reported(client, monkeypatch):
    c, _ = client
    monkeypatch.setattr(studio_app, "fal", FalClient(key=""))
    monkeypatch.delenv("FAL_KEY", raising=False)
    r = c.post("/api/generate", data={"model": "seedance-2.0", "prompt": "x"})
    assert r.status_code == 502 and "FAL_KEY" in r.json()["detail"]


def test_video_route_blocks_path_escape(client):
    c, _ = client
    assert c.get("/videos/..%2Fjobs.json").status_code == 404


def test_page_is_served(client):
    c, _ = client
    assert "Seedance Studio" in c.get("/").text
