"""add NOWPayments enable setting

Revision ID: d10000000006
Revises: d10000000005
Create Date: 2026-11-19
"""
from alembic import op
import sqlalchemy as sa


revision = 'd10000000006'
down_revision = 'd10000000005'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('site_settings', sa.Column('nowpayments_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    op.drop_column('site_settings', 'nowpayments_enabled')
