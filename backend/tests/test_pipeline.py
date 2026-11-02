import json

import pytest

from app.config import Settings
from app.services.llm.client import LLMClient
from app.services.pipeline import PipelineError, run_pipeline
from tests.fakes import FakeOpenAI
from tests.media import ToneTTSEngine, probe, requires_ffmpeg
from tests.test_images import FakeProvider
from tests.test_scenes import GOOD, SCRIPT


def make_settings(tmp_path) -> Settings:
    return Settings(
        proxyapi_key="test", llm_model="primary", llm_fallback_model="fallback",
        storage_dir=tmp_path / "storage", render_fps=15,
    )  # fmt: skip


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_script_to_video_without_paid_calls(tmp_path):
    settings = make_settings(tmp_path)
    fake_llm = FakeOpenAI({"primary": [GOOD]})
    events = []
    result = run_pipeline(
        SCRIPT, style="watercolor", format="9:16", voice="ru-RU-SvetlanaNeural",
        out_dir=tmp_path / "out", settings=settings,
        llm=LLMClient(settings=settings, client=fake_llm, sleep=lambda _: None),
        image_provider=FakeProvider(), tts_engine=ToneTTSEngine(), size=(180, 320),
        on_progress=lambda step, pct, msg: events.append((step, pct)),
    )  # fmt: skip
    assert result.video.exists()
    assert float(probe(result.video)["format"]["duration"]) == pytest.approx(
        result.duration, abs=0.3
    )
    assert [s.name for s in result.steps] == ["scenes", "images", "tts", "render"]
    assert result.cost_rub == pytest.approx(result.steps[0].cost_rub + 3 * 0.5)
    assert events[0] == ("scenes", 0) and events[-1] == ("render", 100)
    report = json.loads(result.report.read_text(encoding="utf-8"))
    assert report["video"] == str(result.video) and len(report["steps"]) == 4
    assert (tmp_path / "out" / "audio" / "narration.json").exists()
    assert report["steps"][3]["detail"]["music"].startswith("calm-")  # auto: mood of the scenes


@requires_ffmpeg
@pytest.mark.ffmpeg
def test_failed_scene_stops_before_render(tmp_path):
    settings = make_settings(tmp_path)
    result_dir = tmp_path / "out"
    llm = LLMClient(settings=settings, client=FakeOpenAI({"primary": [GOOD]}), sleep=lambda _: None)
    with pytest.raises(PipelineError, match="сцена 2"):
        run_pipeline(
            SCRIPT, style="anime", format="16:9", voice="ru-RU-DmitryNeural",
            out_dir=result_dir, settings=settings, llm=llm,
            image_provider=FakeProvider(fail_if="scene 1"), tts_engine=ToneTTSEngine(),
            use_cache=False,
        )  # fmt: skip
    report = json.loads((result_dir / "report.json").read_text(encoding="utf-8"))
    assert "сцена 2" in report["error"]
    assert not (result_dir / "video.mp4").exists()
