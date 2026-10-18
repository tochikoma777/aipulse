"""items.first_seen_at / last_seen_at NOT NULL

Revision ID: f1a2b3c4d5e6
Revises: e6b2f7c1a9d4
Create Date: 2026-10-18 22:10:00.000000

模型把这两列定义为非空（`datetime` 而非 `datetime | None`），但早期迁移建表时是
nullable=True，导致 `alembic check` 长期报 modify_nullable 漂移。
两列都由代码在插入/更新时赋值（first_seen_at 只在首次入库设置，last_seen_at 每次 upsert 更新），
且 c4e8b1a72f90 / d5a2c9b81e34 已对存量行回填，因此收紧为非空是安全的。

SQLite 不支持 ALTER COLUMN，用 batch 模式重建表；alembic 会一并重建索引。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e6b2f7c1a9d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('items') as batch_op:
        batch_op.alter_column('first_seen_at', existing_type=sa.DateTime(), nullable=False)
        batch_op.alter_column('last_seen_at', existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('items') as batch_op:
        batch_op.alter_column('first_seen_at', existing_type=sa.DateTime(), nullable=True)
        batch_op.alter_column('last_seen_at', existing_type=sa.DateTime(), nullable=True)
