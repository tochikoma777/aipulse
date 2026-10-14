"""add llm_usage.error

Revision ID: a3c1d9f2e07b
Revises: 8db72036d522
Create Date: 2026-10-14 22:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # SQLModel 的 AutoString 类型在迁移里需要显式导入


# revision identifiers, used by Alembic.
revision: str = 'a3c1d9f2e07b'
down_revision: Union[str, Sequence[str], None] = '8db72036d522'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # v1.7：记录 json_schema 降级 / 调用失败原因，便于事后审计
    op.add_column(
        'llm_usage',
        sa.Column('error', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('llm_usage', 'error')
