"""KPI report from the database (docs/TZ.md §2, docs/METRICS.md): time, cost, success rate."""

import statistics
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Project, ProjectStatus, RenderJob


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def _spread(values: list[float]) -> dict | None:
    if not values:
        return None
    return {
        "median": round(statistics.median(values), 1),
        "p90": round(_percentile(values, 0.9), 1),
        "max": round(max(values), 1),
    }


def _render_summary(jobs: list[RenderJob]) -> dict:
    finished = [j for j in jobs if j.status in ("done", "failed")]
    done = [j for j in finished if j.status == "done"]
    seconds = [
        (j.finished_at - j.started_at).total_seconds()
        for j in done
        if j.started_at and j.finished_at
    ]
    return {
        "done": len(done),
        "failed": len(finished) - len(done),
        "success_rate": round(len(done) / len(finished), 3) if finished else None,
        "seconds": _spread(seconds),
    }


def compute_stats(db: Session) -> dict:
    """K1 (time to a finished video), K2 (cost), K3 (success rate) from stored projects/jobs.

    `pipeline_seconds` is the sum of the three steps measured by the workers (scenes + images
    + render) for projects that went through all of them; waiting between the user's clicks
    is not counted."""
    projects = db.scalars(select(Project)).all()
    jobs = db.scalars(select(RenderJob)).all()
    complete = [
        p for p in projects
        if p.status == ProjectStatus.done and {"scenes", "images", "render"} <= set(p.timings_json)
    ]  # fmt: skip
    pipeline = [sum(p.timings_json[k] for k in ("scenes", "images", "render")) for p in complete]
    costs = [p.cost_rub for p in projects if p.status == ProjectStatus.done]
    return {
        "projects": {
            "total": len(projects),
            "by_status": dict(Counter(p.status for p in projects)),
        },
        "render_final": _render_summary([j for j in jobs if not j.draft]),
        "render_draft": _render_summary([j for j in jobs if j.draft]),
        "pipeline_seconds": _spread(pipeline),
        "cost_rub": {
            "average_done_project": round(statistics.mean(costs), 2) if costs else None,
            "max_done_project": round(max(costs), 2) if costs else None,
            "total": round(sum(p.cost_rub for p in projects), 2),
        },
    }
