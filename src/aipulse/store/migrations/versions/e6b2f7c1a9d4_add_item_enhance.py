"""add item_enhance table

Revision ID: e6b2f7c1a9d4
Revises: d5a2c9b81e34
Create Date: 2026-10-18 12:20:00.000000

M6b（S1）：条目 LLM 增强结果的持久化落点。
one_liner（要点，一律中文）与 why / stance 分两次调用产出、写同一行；
content_hash / last_hot_score / signals_count 是刷新基线的快照字段。

`item_id` 语义上引用 items.id，但不建 DB 级外键（SQLite 默认不校验，
写约束只会在迁移与删行时制造意外）。downgrade 为 drop_table。
"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b2f7c1a9d4'
down_revision: Union[str, Sequence[str], None] = 'd5a2c9b81e34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'item_enhance',
        sa.Column('item_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('one_liner', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('why', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('stance', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('content_hash', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('last_hot_score', sa.Float(), nullable=False),
        sa.Column('signals_count', sa.Integer(), nullable=False),
        sa.Column('model', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('one_liner_ver', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('enhance_ver', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('created_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.Column('updated_at', sqlmodel.sql.sqltypes.UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint('item_id'),
    )
    op.create_index(
        op.f('ix_item_enhance_updated_at'), 'item_enhance', ['updated_at'], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_item_enhance_updated_at'), table_name='item_enhance')
    op.drop_table('item_enhance')
