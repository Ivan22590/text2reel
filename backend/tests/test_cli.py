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
