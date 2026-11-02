import os
import tempfile

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("CELERY_EAGER", "true")
os.environ.setdefault("STORAGE_DIR", tempfile.mkdtemp(prefix="t2r-test-"))
os.environ.setdefault("RENDER_FPS", "10")
os.environ.setdefault("FFMPEG_PRESET", "ultrafast")
os.environ.setdefault("DEMO_USER", "demo")
os.environ.setdefault("DEMO_PASSWORD", "secret")
os.environ.setdefault("DEMO_MAX_PROJECTS_PER_DAY", "1000")
