"""viva pause/resume support

Revision ID: 0002_viva_pause
Revises: 0001_initial
Create Date: 2026-05-30

Adds two columns to ``viva_sessions`` so an in-progress viva can be paused when
the candidate navigates away and resumed where they left off:

- ``paused_at`` — set while the session is currently paused (NULL otherwise).
- ``total_paused_seconds`` — accumulated paused time, excluded from the
  wall-clock ``session_limit_seconds`` so leaving does not penalise the candidate.

Both are additive and nullable/defaulted, so the migration is safe on a
populated table.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0002_viva_pause"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("viva_sessions", sa.Column("paused_at", sa.DateTime(), nullable=True))
    op.add_column(
        "viva_sessions",
        sa.Column("total_paused_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    # Backfilled existing rows now carry the server default; drop it so the ORM
    # default (0) governs new inserts and the column matches the model.
    op.alter_column("viva_sessions", "total_paused_seconds", server_default=None)


def downgrade() -> None:
    op.drop_column("viva_sessions", "total_paused_seconds")
    op.drop_column("viva_sessions", "paused_at")
