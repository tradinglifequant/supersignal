"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # Tables created via Base.metadata.create_all in startup, but Alembic baseline empty
    # This revision documents intentional baseline - no ops for dev SQLite auto-create
    # In production, run this to establish schema (if tables exist, no-op safe)
    pass

def downgrade() -> None:
    pass
