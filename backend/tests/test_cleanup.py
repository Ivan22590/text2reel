import os
from datetime import UTC, datetime, timedelta

import pytest

from app.config import get_settings
from app.models import Project, RenderJob, Scene
from app.services.cleanup import cleanup_expired
from app.services.project_jobs import project_dir
from tests.dbutil import temp_db

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_dir", tmp_path / "storage")


def add_project(db, age_days: float, status: str = "done", **extra) -> Project:
    when = NOW - timedelta(days=age_days)
    project = Project(script="x", status=status, created_at=when, updated_at=when, **extra)
    db.add(project)
    db.commit()
    directory = project_dir(project.id)
    (directory / "images").mkdir(parents=True)
    (directory / "images" / "scene_00.png").write_bytes(b"x" * 1000)
    return project


def test_expired_projects_are_deleted_with_their_files(tmp_path):
    with temp_db(tmp_path) as db:
        old = add_project(db, age_days=8)
        fresh = add_project(db, age_days=2)
        old_dir, fresh_dir = project_dir(old.id), project_dir(fresh.id)

        report = cleanup_expired(db, ttl_days=7, now=NOW)

        assert report.projects == 1 and report.freed_bytes == 1000
        assert not old_dir.exists() and fresh_dir.exists()
        assert [p.id for p in db.query(Project).all()] == [fresh.id]


def test_children_go_with_the_project(tmp_path):
    with temp_db(tmp_path) as db:
        old = add_project(db, age_days=30)
        db.add(Scene(project_id=old.id, index=0, narration="n"))
        db.add(RenderJob(project_id=old.id, format="9:16"))
        db.commit()
        cleanup_expired(db, ttl_days=7, now=NOW)
        assert db.query(Scene).count() == 0 and db.query(RenderJob).count() == 0


def test_running_projects_are_not_deleted_even_when_old(tmp_path):
    with temp_db(tmp_path) as db:
        add_project(db, age_days=40, status="rendering")
        report = cleanup_expired(db, ttl_days=7, now=NOW)
        # too old to be a live job: recovered instead of deleted
        assert report.projects == 0 and report.recovered == 1
        assert db.query(Project).one().status == "draft"


def test_ttl_zero_keeps_everything_but_still_recovers_stuck_jobs(tmp_path):
    with temp_db(tmp_path) as db:
        add_project(db, age_days=100)
        add_project(db, age_days=1, status="analyzing")
        # analyzing 1 day ago is stuck (> 2 h), so it is recovered; nothing is deleted
        report = cleanup_expired(db, ttl_days=0, now=NOW)
        assert report.projects == 0 and report.recovered == 1 and db.query(Project).count() == 2


def test_stuck_job_returns_to_the_last_stable_state(tmp_path):
    with temp_db(tmp_path) as db:
        stuck = add_project(db, age_days=0.5, status="rendering")
        db.add(Scene(project_id=stuck.id, index=0, narration="n", image_path="i", audio_path="a"))
        db.add(RenderJob(project_id=stuck.id, format="9:16", status="running"))
        recent = add_project(db, age_days=0.01, status="generating")  # 14 min ago: alive
        db.commit()

        report = cleanup_expired(db, ttl_days=7, now=NOW)

        db.refresh(stuck)
        db.refresh(recent)
        assert report.recovered == 1
        assert stuck.status == "assets_ready" and "прервана" in stuck.error
        assert db.query(RenderJob).one().status == "failed"
        assert recent.status == "generating"


def test_old_cache_files_are_removed(tmp_path):
    cache = get_settings().storage_dir / "cache" / "images"
    cache.mkdir(parents=True)
    old, fresh = cache / "old.img", cache / "fresh.img"
    old.write_bytes(b"x" * 10)
    fresh.write_bytes(b"x" * 10)
    stamp = (NOW - timedelta(days=9)).timestamp()
    os.utime(old, (stamp, stamp))
    os.utime(fresh, (NOW.timestamp(), NOW.timestamp()))

    with temp_db(tmp_path) as db:
        report = cleanup_expired(db, ttl_days=7, now=NOW)

    assert report.cache_files == 1 and not old.exists() and fresh.exists()
