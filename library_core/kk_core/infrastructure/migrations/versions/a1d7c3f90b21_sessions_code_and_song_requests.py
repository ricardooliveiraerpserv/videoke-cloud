"""sessions.code + song_requests (Fase D — convidado com aprovação)

Revision ID: a1d7c3f90b21
Revises: 9dcc0f825b0a
Create Date: 2026-11-08 14:10:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'a1d7c3f90b21'
down_revision = '9dcc0f825b0a'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('code', sa.String(length=12), nullable=True))
        batch_op.create_index(batch_op.f('ix_sessions_code'), ['code'], unique=False)

    op.create_table(
        'song_requests',
        sa.Column('session_id', sa.String(length=36), nullable=False),
        sa.Column('song_id', sa.String(length=36), nullable=False),
        sa.Column('song_title', sa.String(length=500), nullable=False),
        sa.Column('artists_text', sa.String(length=500), nullable=False),
        sa.Column('singer', sa.String(length=200), nullable=False),
        sa.Column('note', sa.Text(), nullable=False),
        sa.Column('device', sa.String(length=80), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('queue_item_id', sa.String(length=36), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['song_id'], ['songs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('song_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_song_requests_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_song_requests_status'), ['status'], unique=False)
        batch_op.create_index('ix_song_requests_session_status', ['session_id', 'status'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('song_requests', schema=None) as batch_op:
        batch_op.drop_index('ix_song_requests_session_status')
        batch_op.drop_index(batch_op.f('ix_song_requests_status'))
        batch_op.drop_index(batch_op.f('ix_song_requests_session_id'))
    op.drop_table('song_requests')

    with op.batch_alter_table('sessions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sessions_code'))
        batch_op.drop_column('code')
