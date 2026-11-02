import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.db import SessionLocal
from app.main import app
from app.models import Project, Scene
from app.services import providers
from app.services.llm.client import LLMClient
from tests.fakes import FakeOpenAI
from tests.media import ToneTTSEngine, probe, requires_ffmpeg
from tests.test_images import FakeProvider
from tests.test_scenes import GOOD, SCRIPT
from tests.test_tts import FakeEngine

LLM_SETTINGS = Settings(proxyapi_key="t", llm_model="primary", llm_fallback_model="fallback")


class Fakes:
    def __init__(self):
        self.llm_answers = [GOOD]
        self.images = FakeProvider()
        self.tts = FakeEngine()

    def llm(self):
        fake = FakeOpenAI({"primary": list(self.llm_answers), "fallback": []})
        return LLMClient(settings=LLM_SETTINGS, client=fake, sleep=lambda _: None)


@pytest.fixture
def fakes():
    f = Fakes()
    providers.overrides.update(llm=f.llm, image_provider=lambda: f.images, tts_engine=lambda: f.tts)
    yield f
    providers.overrides.clear()


@pytest.fixture
def client(fakes):
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"username": "demo", "password": "secret"}).is_success
        yield c


def new_project(client, **extra) -> dict:
    body = {"script": SCRIPT, "style": "watercolor", "format": "9:16", **extra}
    resp = client.post("/api/projects", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def analyzed(client, **extra) -> dict:
    project = new_project(client, **extra)
    assert client.post(f"/api/projects/{project['id']}/analyze").status_code == 202
    return client.get(f"/api/projects/{project['id']}").json()


def generated(client) -> dict:
    project = analyzed(client)
    assert client.post(f"/api/projects/{project['id']}/generate").status_code == 202
    return client.get(f"/api/projects/{project['id']}").json()


def test_auth_required_and_login(fakes):
    with TestClient(app) as c:
        assert c.get("/api/projects").status_code == 401
        assert (
            c.post("/api/auth/login", json={"username": "demo", "password": "x"}).status_code == 401
        )
        c.post("/api/auth/login", json={"username": "demo", "password": "secret"})
        assert c.get("/api/auth/me").json() == {"username": "demo"}
        c.cookies.set("t2r_session", "demo:forged")
        assert c.get("/api/projects").status_code == 401


def test_meta(client):
    data = client.get("/api/meta").json()
    assert len(data["styles"]) == 6 and len(data["voices"]) == 5
    assert {f["id"] for f in data["formats"]} == {"9:16", "16:9", "1:1"}


def test_create_validates_and_limits(client, monkeypatch):
    project = new_project(client)
    assert project["status"] == "draft" and project["title"].startswith("Лиса")
    assert client.post("/api/projects", json={"script": "x", "style": "nope"}).status_code == 422
    monkeypatch.setattr(get_settings(), "demo_max_projects_per_day", 0)
    assert client.post("/api/projects", json={"script": "x"}).status_code == 429


def test_analyze_creates_scenes(client):
    project = analyzed(client)
    assert project["status"] == "scenes_ready"
    assert [s["index"] for s in project["scenes"]] == [0, 1, 2]
    assert project["cost_rub"] >= 0 and project["progress"] == 100


def test_analyze_failure_is_reported(client, fakes):
    fakes.llm_answers = ["not json"] * 3
    project = analyzed(client, style="comic")  # other style: no cached storyboard
    assert project["status"] == "draft"
    assert "Не удалось разбить сценарий" in project["error"]


def test_generate_assets_and_serve_files(client):
    project = generated(client)
    assert project["status"] == "assets_ready"
    scene = project["scenes"][0]
    assert scene["status"] == "ready" and scene["duration"] > 0
    image = client.get(scene["image_url"])
    assert image.status_code == 200 and image.content.startswith(b"\x89PNG")
    assert client.get("/api/files/../../etc/passwd").status_code == 404


def test_edit_narration_regenerates_only_audio(client, fakes):
    project = generated(client)
    scene = project["scenes"][1]
    images_before = len(fakes.images.requests)
    resp = client.patch(f"/api/scenes/{scene['id']}", json={"narration": "Новый текст сцены."})
    assert resp.json()["audio_url"] is None and resp.json()["image_url"] is not None
    assert client.get(f"/api/projects/{project['id']}").json()["status"] == "scenes_ready"

    client.post(f"/api/projects/{project['id']}/generate")
    after = client.get(f"/api/projects/{project['id']}").json()
    assert after["status"] == "assets_ready"
    assert len(fakes.images.requests) == images_before  # no paid image call
    assert ("Новый текст сцены.", "ru-RU-SvetlanaNeural", "+0%", "+0Hz") in fakes.tts.calls


def test_regenerate_image_with_hint_uses_new_prompt_and_seed(client, fakes):
    project = generated(client)
    scene = project["scenes"][0]
    fakes.llm_answers = [json.dumps({"visual_prompt": "the fox at night under the stars"})]
    resp = client.post(
        f"/api/scenes/{scene['id']}/regenerate", json={"target": "image", "hint": "ночью"}
    )
    assert resp.status_code == 202
    after = client.get(f"/api/projects/{project['id']}").json()
    assert after["scenes"][0]["visual_prompt"] == "the fox at night under the stars"
    assert after["status"] == "assets_ready"
    with SessionLocal() as db:
        assert db.get(Scene, scene["id"]).image_seed == 1
        project_seed = db.get(Project, project["id"]).seed
    assert "under the stars" in fakes.images.requests[-1].prompt
    assert fakes.images.requests[-1].seed == project_seed + 1  # a new image, not the cached one


def test_style_change_invalidates_images(client):
    project = generated(client)
    resp = client.patch(f"/api/projects/{project['id']}", json={"style": "anime"})
    data = resp.json()
    assert data["status"] == "scenes_ready"
    assert all(s["image_url"] is None and s["audio_url"] for s in data["scenes"])


def test_timeline_and_events(client):
    project = generated(client)
    timeline = client.get(f"/api/projects/{project['id']}/timeline").json()
    assert timeline["ready"] and len(timeline["scenes"]) == 3
    assert timeline["scenes"][1]["start"] > 0 and timeline["cues"]
    with client.stream("GET", f"/api/projects/{project['id']}/events") as resp:
        body = "".join(resp.iter_text())
    event = json.loads(body.split("data: ", 1)[1].split("\n\n")[0])
    assert event["status"] == "assets_ready"


def test_render_requires_assets(client):
    project = analyzed(client)
    assert client.post(f"/api/projects/{project['id']}/render", json={}).status_code == 409


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_render_produces_video(client, fakes):
    fakes.tts = ToneTTSEngine()
    project = generated(client)
    resp = client.post(f"/api/projects/{project['id']}/render", json={})
    assert resp.status_code == 202
    after = client.get(f"/api/projects/{project['id']}").json()
    assert after["status"] == "done", after["error"]
    job = after["renders"][0]
    assert job["status"] == "done" and job["video_url"]
    video = client.get(job["video_url"])
    assert video.status_code == 200
    path = get_settings().storage_dir / job["video_url"].split("/api/files/")[1].split("?")[0]
    assert probe(path)["streams"][0]["width"] == 1080


def test_parse_txt_and_docx(client):
    txt = client.post(
        "/api/scripts/parse", files={"file": ("s.txt", "Привет, мир".encode("cp1251"))}
    )
    assert txt.json()["text"] == "Привет, мир"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as docx:
        docx.writestr("word/document.xml", (
            '<w:document><w:body><w:p><w:r><w:t>Первый абзац</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Второй </w:t></w:r><w:r><w:t>абзац</w:t></w:r>'
            "</w:p></w:body></w:document>"
        ))  # fmt: skip
    resp = client.post("/api/scripts/parse", files={"file": ("s.docx", buf.getvalue())})
    assert resp.json()["text"] == "Первый абзац\nВторой абзац"
    assert client.post("/api/scripts/parse", files={"file": ("a.pdf", b"x")}).status_code == 415


def png_bytes(color=(0, 160, 255, 255)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGBA", (120, 60), color).save(buf, "PNG")
    return buf.getvalue()


def test_meta_lists_music_fonts_and_templates(client):
    data = client.get("/api/meta").json()
    assert len(data["music"]) >= 10 and data["music"][0]["url"].startswith("/api/music/")
    assert {f["id"] for f in data["fonts"]} == {"PT Sans", "Fira Sans", "Lobster", "Russo One"}
    assert {t["format"] for t in data["templates"]} == {"9:16", "16:9", "1:1"}
    assert "top-right" in data["logo_positions"]


def test_music_preview_file(client, fakes):
    track = client.get("/api/meta").json()["music"][0]
    resp = client.get(track["url"])
    assert resp.status_code == 200 and resp.headers["content-type"] == "audio/ogg"
    assert resp.content[:4] == b"OggS"
    assert client.get("/api/music/nope").status_code == 404
    with TestClient(app) as anonymous:
        assert anonymous.get(track["url"]).status_code == 401


def test_create_with_music_and_branding(client):
    project = new_project(
        client, music="epic-endgame",
        branding={"font": "Lobster", "intro_text": "Привет", "accent_color": "#ff0000"},
    )  # fmt: skip
    assert project["music"] == "epic-endgame"
    assert project["branding"]["font"] == "Lobster"
    assert project["branding"]["accent_color"] == "#FF0000" and not project["branding"]["has_logo"]
    assert client.post("/api/projects", json={"script": "x", "music": "nope"}).status_code == 422
    bad_font = client.post("/api/projects", json={"script": "x", "branding": {"font": "Arial"}})
    assert bad_font.status_code == 422


def test_auto_music_follows_scene_mood(client):
    project = analyzed(client)
    assert project["music"] == "auto" and project["music_track"]["id"].startswith("calm-")
    off = client.patch(f"/api/projects/{project['id']}", json={"music": "none"}).json()
    assert off["music"] == "none" and off["music_track"] is None
    assert client.patch(f"/api/projects/{project['id']}", json={"music": "x"}).status_code == 422


def test_music_and_branding_changes_keep_generated_assets(client):
    project = generated(client)
    resp = client.patch(
        f"/api/projects/{project['id']}",
        json={"music": "happy-badinerie", "branding": {"intro_text": "Hi", "font": "PT Sans"}},
    )
    data = resp.json()
    assert data["status"] == "assets_ready"  # nothing to regenerate
    assert all(s["image_url"] and s["audio_url"] for s in data["scenes"])
    assert data["music_track"]["id"] == "happy-badinerie" and data["branding"]["intro_text"] == "Hi"


def test_logo_upload_and_delete(client):
    pid = new_project(client)["id"]
    resp = client.post(f"/api/projects/{pid}/logo", files={"file": ("l.png", png_bytes())})
    branding = resp.json()["branding"]
    assert resp.status_code == 200 and branding["has_logo"]
    assert client.get(branding["logo_url"]).content.startswith(b"\x89PNG")
    bad = client.post(f"/api/projects/{pid}/logo", files={"file": ("l.png", b"not an image")})
    assert bad.status_code == 422 and "прочитать" in bad.json()["detail"]
    assert client.delete(f"/api/projects/{pid}/logo").json()["branding"]["has_logo"] is False


def test_timeline_includes_cards_and_music(client):
    project = generated(client)
    pid = project["id"]
    plain = client.get(f"/api/projects/{pid}/timeline").json()
    assert [s["kind"] for s in plain["scenes"]] == ["scene"] * 3

    client.patch(
        f"/api/projects/{pid}", json={"branding": {"intro_text": "In", "outro_text": "Out"}}
    )
    framed = client.get(f"/api/projects/{pid}/timeline").json()
    assert [s["kind"] for s in framed["scenes"]] == ["intro", "scene", "scene", "scene", "outro"]
    assert framed["scenes"][0]["id"] is None and framed["scenes"][0]["start"] == 0
    assert framed["scenes"][1]["start"] > 2  # narration starts after the intro card
    assert framed["total"] > plain["total"] + 4 and framed["music"]["id"].startswith("calm-")


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_branded_render_matches_planned_timeline(client, fakes):
    fakes.tts = ToneTTSEngine()
    pid = generated(client)["id"]
    client.post(f"/api/projects/{pid}/logo", files={"file": ("l.png", png_bytes())})
    client.patch(
        f"/api/projects/{pid}",
        json={"music": "happy-badinerie",
              "branding": {"intro_text": "Привет!", "outro_text": "Спасибо!", "font": "PT Sans"}},
    )  # fmt: skip
    planned = client.get(f"/api/projects/{pid}/timeline").json()["total"]
    assert client.post(f"/api/projects/{pid}/render", json={}).status_code == 202
    after = client.get(f"/api/projects/{pid}").json()
    assert after["status"] == "done", after["error"]
    url = after["renders"][0]["video_url"]
    video = get_settings().storage_dir / url.split("/api/files/")[1].split("?")[0]
    assert float(probe(video)["format"]["duration"]) == pytest.approx(planned, abs=0.3)


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_draft_render_is_a_480p_preview(client, fakes):
    fakes.tts = ToneTTSEngine()
    pid = generated(client)["id"]
    resp = client.post(f"/api/projects/{pid}/render", json={"draft": True})
    assert resp.status_code == 202 and resp.json()["draft"] is True
    after = client.get(f"/api/projects/{pid}").json()
    assert after["status"] == "done", after["error"]
    job = after["renders"][0]
    assert job["draft"] is True
    video = get_settings().storage_dir / job["video_url"].split("/api/files/")[1].split("?")[0]
    stream = probe(video)["streams"][0]
    assert (stream["width"], stream["height"]) == (480, 854)


def test_pipeline_timings_are_recorded_for_the_kpi_report(client):
    project = generated(client)
    with SessionLocal() as db:
        timings = db.get(Project, project["id"]).timings_json
    assert set(timings) == {"scenes", "images"} and all(v >= 0 for v in timings.values())
