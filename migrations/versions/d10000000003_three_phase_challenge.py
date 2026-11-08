"""add third phase challenge rules and start timestamp

Revision ID: d10000000003
Revises: d10000000002
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa


revision = 'd10000000003'
down_revision = 'd10000000002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('challenge_template', sa.Column('phase3_target', sa.Float(), nullable=True))
    op.add_column('challenge_template', sa.Column('phase3_daily_loss', sa.Float(), nullable=True))
    op.add_column('challenge_template', sa.Column('phase3_daily_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
    op.add_column('challenge_template', sa.Column('phase3_overall_loss', sa.Float(), nullable=True))
    op.add_column('challenge_template', sa.Column('phase3_overall_dd_type', sa.String(length=20), nullable=False, server_default='equity'))
    op.add_column('challenge_template', sa.Column('phase3_min_days', sa.Integer(), nullable=True))
    op.add_column('challenge_template', sa.Column('phase3_duration', sa.Integer(), nullable=True))
    op.add_column('challenge_template', sa.Column('phase3_leverage', sa.String(length=20), nullable=True))
    op.add_column('challenge_template', sa.Column('phase3_rules', sa.Text(), nullable=True))
    op.add_column('challenge_purchase', sa.Column('phase3_started_at', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('challenge_purchase', 'phase3_started_at')
    op.drop_column('challenge_template', 'phase3_rules')
    op.drop_column('challenge_template', 'phase3_leverage')
    op.drop_column('challenge_template', 'phase3_duration')
    op.drop_column('challenge_template', 'phase3_min_days')
    op.drop_column('challenge_template', 'phase3_overall_dd_type')
    op.drop_column('challenge_template', 'phase3_overall_loss')
    op.drop_column('challenge_template', 'phase3_daily_dd_type')
    op.drop_column('challenge_template', 'phase3_daily_loss')
    op.drop_column('challenge_template', 'phase3_target')
