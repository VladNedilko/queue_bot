"""Add per-session activity confirmation state."""
from alembic import op
import sqlalchemy as sa

revision = "0002_session_confirmations"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

def upgrade():
    if "session_confirmations" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "session_confirmations",
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("proxy_sessions.id"), primary_key=True),
        sa.Column("last_confirmed_at", sa.DateTime(), nullable=False),
        sa.Column("requested_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
    )

def downgrade():
    if "session_confirmations" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("session_confirmations")
