from fastapi.testclient import TestClient

from app.main import app


def test_health_ok():
    with TestClient(app) as client:
        resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_celery_ping_eager():
    from app.workers.celery_app import ping

    assert ping.delay().get() == "pong"


def test_cleanup_task_runs_and_reports():
    from app.workers.tasks import cleanup

    report = cleanup.delay().get()
    assert set(report) == {"projects", "cache_files", "freed_bytes", "recovered"}
