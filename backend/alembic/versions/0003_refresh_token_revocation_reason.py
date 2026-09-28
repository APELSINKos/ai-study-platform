"""refresh token revocation reason

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-28 09:28:20.074470

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "refresh_tokens", sa.Column("revocation_reason", sa.String(length=32), nullable=True)
    )
    # Autogenerate does not detect CHECK constraints; added by hand to match the model.
    op.create_check_constraint(
        op.f("ck_refresh_tokens_revocation_reason_valid"),
        "refresh_tokens",
        "revocation_reason IN ('rotated', 'signed_out', 'reuse_detected')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f("ck_refresh_tokens_revocation_reason_valid"), "refresh_tokens")
    op.drop_column("refresh_tokens", "revocation_reason")
