"""init tables

Revision ID: 0001
Revises:
Create Date: 2026-09-12

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

EMBED_DIM = 768


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_app", sa.String, nullable=True),
        sa.Column("raw_asr", sa.Text, nullable=False),
        sa.Column("formatted_text", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_episodes_user_id", "episodes", ["user_id"])
    op.create_index("ix_episodes_occurred_at", "episodes", ["occurred_at"])
    op.create_index("ix_episodes_source_app", "episodes", ["source_app"])
    # IVFFlat needs data to be useful; lists=100 also fails on tiny tables.
    # Create a simple vector index; operators still work via pgvector.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_episodes_embedding ON episodes "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10)"
    )

    op.create_table(
        "facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subject", sa.String, nullable=False),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("status", sa.String, nullable=True, server_default="active"),
        sa.Column("source_episode_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_facts_user_id", "facts", ["user_id"])
    op.create_index("ix_facts_subject", "facts", ["subject"])

    op.create_table(
        "preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("category", sa.String, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("strength", sa.Float, nullable=False, server_default="0.5"),
        sa.Column("evidence_count", sa.Integer, nullable=True, server_default="1"),
        sa.Column("source_episode_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False),
        sa.Column("status", sa.String, nullable=True, server_default="active"),
        sa.Column("embedding", Vector(EMBED_DIM), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_preferences_user_id", "preferences", ["user_id"])
    op.create_index("ix_preferences_category", "preferences", ["category"])

    op.create_table(
        "memory_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("episodes.id"), nullable=False),
        sa.Column("event_type", sa.String, nullable=False),
        sa.Column("target_table", sa.String, nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("raw_candidate", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_memory_events_user_id", "memory_events", ["user_id"])


def downgrade():
    op.drop_table("memory_events")
    op.drop_table("preferences")
    op.drop_table("facts")
    op.drop_table("episodes")
    op.execute("DROP EXTENSION IF EXISTS vector")
