<%
    import re

    body = (upgrades or "") + (downgrades or "")
    needs_op = bool(re.search(r"\bop\.", body))
    needs_sa = bool(re.search(r"\bsa\.", body))

    def literal(value):
        """Render like repr(), but with double quotes to match ruff format."""
        return f'"{value}"' if isinstance(value, str) else repr(value)
%>\
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""

from collections.abc import Sequence
% if needs_op or needs_sa or imports:

% endif
% if needs_sa:
import sqlalchemy as sa
% endif
% if needs_op:
from alembic import op
% endif
% if imports:
${imports}
% endif

# revision identifiers, used by Alembic.
revision: str = ${literal(up_revision)}
down_revision: str | Sequence[str] | None = ${literal(down_revision)}
branch_labels: str | Sequence[str] | None = ${literal(branch_labels)}
depends_on: str | Sequence[str] | None = ${literal(depends_on)}


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
