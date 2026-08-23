"""Add a family/content hash uniqueness gate for immutable candidate Bundles."""

from __future__ import annotations

from alembic import op

revision = "20260824_0002_b1_bundle_dedupe"
down_revision = "20260824_0001_b1_shadow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_evidence_bundles_family_content",
        "evidence_bundles",
        ["family_id", "content_hash"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_evidence_bundles_family_content", table_name="evidence_bundles")
