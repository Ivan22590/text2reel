"""Initial schema: projects, scenes, render jobs.

Revision ID: 0001
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("style", sa.String(32), nullable=False),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("voice", sa.String(64), nullable=False),
        sa.Column("music_track_id", sa.String(64), nullable=True),
        sa.Column("branding_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("style_bible", sa.JSON(), nullable=True),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("message", sa.String(300), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("cost_rub", sa.Float(), nullable=False),
        sa.Column("timings_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "scenes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("narration", sa.Text(), nullable=False),
        sa.Column("visual_prompt", sa.Text(), nullable=False),
        sa.Column("mood", sa.String(16), nullable=False),
        sa.Column("camera", sa.String(16), nullable=False),
        sa.Column("image_seed", sa.Integer(), nullable=False),
        sa.Column("image_path", sa.String(512), nullable=True),
        sa.Column("audio_path", sa.String(512), nullable=True),
        sa.Column("duration_sec", sa.Float(), nullable=True),
        sa.Column("words_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_scenes_project_id", "scenes", ["project_id"])
    op.create_table(
        "render_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.String(8), nullable=False),
        sa.Column("draft", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("step", sa.String(32), nullable=False),
        sa.Column("output_path", sa.String(512), nullable=True),
        sa.Column("srt_path", sa.String(512), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=False),
        sa.Column("tokens_out", sa.Integer(), nullable=False),
        sa.Column("images_count", sa.Integer(), nullable=False),
        sa.Column("cost_rub", sa.Float(), nullable=False),
    )
    op.create_index("ix_render_jobs_project_id", "render_jobs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_render_jobs_project_id", table_name="render_jobs")
    op.drop_table("render_jobs")
    op.drop_index("ix_scenes_project_id", table_name="scenes")
    op.drop_table("scenes")
    op.drop_table("projects")
