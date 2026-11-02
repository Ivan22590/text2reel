from datetime import UTC, datetime, timedelta

from app.models import Project, RenderJob
from app.services.stats import compute_stats
from tests.dbutil import temp_db

T0 = datetime(2026, 11, 1, 10, 0, tzinfo=UTC)


def done_project(db, cost: float, scenes: float, images: float, render: float) -> Project:
    project = Project(
        script="x", status="done", cost_rub=cost,
        timings_json={"scenes": scenes, "images": images, "render": render},
    )  # fmt: skip
    db.add(project)
    db.commit()
    return project


def job(db, project, seconds: float | None, status="done", draft=False) -> None:
    started = T0
    finished = None if seconds is None else T0 + timedelta(seconds=seconds)
    db.add(RenderJob(project_id=project.id, format="9:16", status=status, draft=draft,
                     started_at=started, finished_at=finished))  # fmt: skip
    db.commit()


def test_empty_database_gives_empty_report(tmp_path):
    with temp_db(tmp_path) as db:
        stats = compute_stats(db)
    assert stats["projects"]["total"] == 0 and stats["pipeline_seconds"] is None
    assert stats["render_final"]["success_rate"] is None
    assert stats["cost_rub"]["average_done_project"] is None


def test_kpis_from_projects_and_jobs(tmp_path):
    with temp_db(tmp_path) as db:
        a = done_project(db, cost=4.0, scenes=5, images=40, render=60)  # 105 s
        b = done_project(db, cost=6.0, scenes=7, images=50, render=100)  # 157 s
        c = done_project(db, cost=8.0, scenes=6, images=45, render=80)  # 131 s
        job(db, a, 60)
        job(db, b, 100)
        job(db, c, 80)
        job(db, c, None, status="failed")  # a failed render
        job(db, a, 12, draft=True)  # drafts are reported separately
        db.add(Project(script="y", status="draft", cost_rub=0.5))  # unfinished: not in K2 average
        db.commit()

        stats = compute_stats(db)

    assert stats["projects"]["by_status"] == {"done": 3, "draft": 1}
    final = stats["render_final"]
    assert (final["done"], final["failed"], final["success_rate"]) == (3, 1, 0.75)
    assert final["seconds"] == {"median": 80.0, "p90": 100.0, "max": 100.0}
    assert stats["render_draft"]["done"] == 1 and stats["render_draft"]["seconds"]["median"] == 12.0
    assert (
        stats["pipeline_seconds"]["median"] == 131.0 and stats["pipeline_seconds"]["max"] == 157.0
    )
    assert stats["cost_rub"] == {
        "average_done_project": 6.0,
        "max_done_project": 8.0,
        "total": 18.5,
    }


def test_project_without_all_timings_is_not_in_pipeline_kpi(tmp_path):
    with temp_db(tmp_path) as db:
        db.add(Project(script="x", status="done", timings_json={"scenes": 5, "images": 30}))
        db.commit()
        assert compute_stats(db)["pipeline_seconds"] is None
