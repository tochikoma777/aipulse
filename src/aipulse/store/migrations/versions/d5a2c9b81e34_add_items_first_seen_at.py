"""add items.first_seen_at

Revision ID: d5a2c9b81e34
Revises: c4e8b1a72f90
Create Date: 2026-10-17 16:00:00.000000

v1.15：时间语义第三态 discovery（arXiv / HF 索引滞后 3-4 天）。
存量行用 collected_at 回填；之后 upsert 只在插入时设置，永不覆盖。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5a2c9b81e34'
down_revision: Union[str, Sequence[str], None] = 'c4e8b1a72f90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('items', sa.Column('first_seen_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE items SET first_seen_at = collected_at WHERE first_seen_at IS NULL")
    op.create_index('ix_items_first_seen_at', 'items', ['first_seen_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_items_first_seen_at', table_name='items')
    op.drop_column('items', 'first_seen_at')
