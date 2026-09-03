"""Add durable Dianping shop-profile fields to ``restaurants``.

Comment evidence remains in its own lifecycle.  These columns hold only the
low-frequency structured shop projection and the raw provider snapshot needed
for refresh/audit.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision = "20260904_0010_shop_profile"
down_revision = "20260825_0008_legacy_schema"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("region", sa.String(length=100), None),
    ("provider_refs", postgresql.JSONB(), sa.text("'{}'::jsonb")),
    ("profile_url", sa.Text(), None),
    ("source_url", sa.Text(), None),
    ("image_url", sa.Text(), None),
    ("category", sa.String(length=150), None),
    ("review_count", sa.Integer(), None),
    ("average_price", sa.Float(), None),
    ("latitude", sa.Float(), None),
    ("longitude", sa.Float(), None),
    ("coordinate_system", sa.String(length=32), None),
    ("geo", postgresql.JSONB(), sa.text("'{}'::jsonb")),
    ("recommended_dishes", postgresql.JSONB(), sa.text("'[]'::jsonb")),
    ("promotions", postgresql.JSONB(), sa.text("'[]'::jsonb")),
    ("profile_metadata", postgresql.JSONB(), sa.text("'{}'::jsonb")),
    ("review_completeness", postgresql.JSONB(), sa.text("'{}'::jsonb")),
    ("profile_gaps", postgresql.JSONB(), sa.text("'[]'::jsonb")),
    ("source_payload", postgresql.JSONB(), None),
    ("source_updated_at", sa.DateTime(timezone=True), None),
    ("profile_fetched_at", sa.DateTime(timezone=True), None),
    ("profile_refresh_status", sa.String(length=20), None),
)


def upgrade() -> None:
    if context.is_offline_mode():
        for name, type_, default in _COLUMNS:
            op.add_column(
                "restaurants",
                sa.Column(name, type_, nullable=True, server_default=default),
                if_not_exists=True,
            )
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("restaurants")}
    for name, type_, default in _COLUMNS:
        if name in existing:
            continue
        op.add_column(
            "restaurants",
            sa.Column(name, type_, nullable=True, server_default=default),
            if_not_exists=True,
        )


def downgrade() -> None:
    if context.is_offline_mode():
        for name, _, _ in reversed(_COLUMNS):
            op.drop_column("restaurants", name, if_exists=True)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("restaurants")}
    for name, _, _ in reversed(_COLUMNS):
        if name in existing:
            op.drop_column("restaurants", name)
