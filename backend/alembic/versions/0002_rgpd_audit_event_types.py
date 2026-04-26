"""RGPD — ajout audit_event_type : user.data_exported + user.delete_requested

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-26

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE audit_event_type ADD VALUE IF NOT EXISTS 'user.data_exported'")
    op.execute("ALTER TYPE audit_event_type ADD VALUE IF NOT EXISTS 'user.delete_requested'")


def downgrade() -> None:
    # Les valeurs d'enum PostgreSQL ne peuvent pas être supprimées sans recréer le type.
    # En cas de rollback, les nouvelles valeurs restent mais ne sont plus utilisées.
    pass
