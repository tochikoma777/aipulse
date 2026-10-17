"""add items.last_seen_at

Revision ID: c4e8b1a72f90
Revises: a3c1d9f2e07b
Create Date: 2026-10-17 15:20:00.000000

v1.14：状态型源（GitHub Trending）没有发布时间，窗口过滤必须看"最近一次仍被采到"。
存量行用 collected_at 回填；今后每次 upsert 都无条件更新。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4e8b1a72f90'
down_revision: Union[str, Sequence[str], None] = 'a3c1d9f2e07b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 先允许 NULL 以便 SQLite 加列，再用 collected_at 回填，最后建索引。
    op.add_column('items', sa.Column('last_seen_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE items SET last_seen_at = collected_at WHERE last_seen_at IS NULL")
    op.create_index('ix_items_last_seen_at', 'items', ['last_seen_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_items_last_seen_at', table_name='items')
    op.drop_column('items', 'last_seen_at')
