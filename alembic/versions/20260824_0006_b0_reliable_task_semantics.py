"""Add the Alembic-owned B0 reliable task authority tables."""

from __future__ import annotations

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20260824_0006_b0_reliable_task"
down_revision = "20260824_0005_b2_derivations"
branch_labels = None
depends_on = None


def _tables() -> tuple[Table, Table, Table]:
    metadata = MetaData()
    reliable_tasks = Table(
        "reliable_tasks",
        metadata,
        Column("task_id", String(256), primary_key=True),
        Column("workflow_id", String(256), nullable=False, unique=True),
        Column("status", String(32), nullable=False),
        Column("turn_id", String(128), nullable=False),
        Column("run_id", String(256)),
        Column("task_payload", JSONB, nullable=False),
        Column("request_payload", JSONB, nullable=False),
        Column(
            "created_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    reliable_task_results = Table(
        "reliable_task_results",
        metadata,
        Column("result_id", Integer, primary_key=True),
        Column("task_id", String(256), nullable=False),
        Column("workflow_id", String(256), nullable=False),
        Column("run_id", String(256), nullable=False),
        Column("status", String(32), nullable=False),
        Column("payload", JSONB, nullable=False),
        Column("idempotency_key", String(512), nullable=False, unique=True),
        Column(
            "result_version",
            String(512),
            nullable=False,
        ),
        Column(
            "committed_at",
            DateTime(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
        UniqueConstraint(
            "task_id",
            "workflow_id",
            "run_id",
            name="uq_reliable_task_results_identity",
        ),
    )
    task_progress_projection = Table(
        "task_progress_projection",
        metadata,
        Column("task_id", String(256), primary_key=True),
        Column("payload", JSONB, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    return reliable_tasks, reliable_task_results, task_progress_projection


def upgrade() -> None:
    """Provision B0 tables without inspecting or changing legacy tables."""

    for table in _tables():
        op.create_table(table.name, *table.columns, *table.constraints)


def downgrade() -> None:
    """Remove only the additive B0 tables during an explicit rollback drill."""

    for table in reversed(_tables()):
        op.drop_table(table.name)
