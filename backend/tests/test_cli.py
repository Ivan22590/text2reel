import json

import pytest

from app import cli


def test_music_command_lists_the_library(capsys):
    assert cli.main(["music"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) >= 10 and any(line.startswith("calm-blue-whale") for line in lines)


def test_music_argument(tmp_path):
    assert cli._music_arg("auto") == "auto" and cli._music_arg("none") == "none"
    assert cli._music_arg("epic-endgame") == "epic-endgame"
    audio = tmp_path / "own.mp3"
    audio.write_bytes(b"x")
    assert cli._music_arg(str(audio)) == audio
    with pytest.raises(SystemExit, match="unknown --music"):
        cli._music_arg("no-such-track")


def test_branding_arguments(tmp_path):
    parser = cli.build_parser()
    brand = tmp_path / "brand.json"
    brand.write_text(json.dumps({"accent_color": "#00ff00", "intro_text": "from file"}))
    args = parser.parse_args(
        [
            "render",
            "s.txt",
            "--branding",
            str(brand),
            "--outro-text",
            "Bye",
            "--font",
            "Lobster",
            "--logo",
            "logo.png",
        ]  # fmt: skip
    )
    branding, logo = cli._branding_args(args)
    assert branding.accent_color == "#00FF00" and branding.intro_text == "from file"
    assert branding.outro_text == "Bye" and branding.font == "Lobster" and str(logo) == "logo.png"


def test_cleanup_and_stats_commands(capsys):
    assert cli.main(["cleanup", "--ttl-days", "0"]) == 0
    assert "projects deleted: 0" in capsys.readouterr().out
    assert cli.main(["stats", "--json"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert {"projects", "render_final", "pipeline_seconds", "cost_rub"} <= set(stats)
    assert cli.main(["stats"]) == 0 and "K1 pipeline seconds" in capsys.readouterr().out


def test_smoke_image_reports_size_time_and_cost(tmp_path, monkeypatch, capsys):
    import io

    from PIL import Image

    from app.services.images import ImageResult

    buf = io.BytesIO()
    Image.new("RGB", (1024, 1536), (10, 20, 30)).save(buf, "PNG")

    class FakeProvider:
        name, model = "proxyapi", "some-model"

        def generate(self, request):
            assert (request.width, request.height) == (768, 1344)
            info = {"size": "1024x1536", "tokens_in": 12, "tokens_out": 345}
            return ImageResult(buf.getvalue(), self.name, self.model, 0.42, info)

    monkeypatch.setattr(cli, "get_provider", lambda settings: FakeProvider())
    out = tmp_path / "fox.png"
    assert cli.main(["smoke-image", "--out", str(out)]) == 0
    line = capsys.readouterr().out
    assert "proxyapi/some-model" in line and "asked 1024x1536, got 1024x1536" in line
    assert (
        "tokens 12/345" in line and "0.42 RUB" in line and out.read_bytes().startswith(b"\x89PNG")
    )


def test_smoke_image_failure_is_reported(monkeypatch, capsys):
    from app.services.images import ImageError

    def broken(settings):
        raise ImageError("PROXYAPI_KEY is not set")

    monkeypatch.setattr(cli, "get_provider", broken)
    assert cli.main(["smoke-image"]) == 1
    assert "FAIL: PROXYAPI_KEY is not set" in capsys.readouterr().out


def test_image_models_lists_cheapest_first_with_prices(monkeypatch, capsys):
    from types import SimpleNamespace

    ids = [
        "openai/gpt-image-2", "anthropic/claude-haiku-5-5", "black-forest-labs/flux-3-image-klein",
        "newvendor/brand-new-image", "qwen/qwen-image-2.1-turbo",
    ]  # fmt: skip
    listing = SimpleNamespace(list=lambda: [SimpleNamespace(id=i) for i in ids])
    client = SimpleNamespace(client=SimpleNamespace(models=listing))
    monkeypatch.setattr(cli, "LLMClient", lambda: client)
    assert cli.main(["image-models"]) == 0
    lines = capsys.readouterr().out.splitlines()
    shown = [line.split()[0] for line in lines[:-1]]
    # text models are not listed; image models absent from the table come last
    assert shown == [
        "black-forest-labs/flux-3-image-klein", "qwen/qwen-image-2.1-turbo",
        "openai/gpt-image-2", "newvendor/brand-new-image",
    ]  # fmt: skip
    assert "263.16" in lines[0] and "not in the price table" in lines[3]
