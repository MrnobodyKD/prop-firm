"""add generic manual payment methods

Revision ID: d10000000001
Revises: c4b9710e2a6d
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'd10000000001'
down_revision = 'c4b9710e2a6d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'payment_method',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('type', sa.String(length=40), nullable=False, server_default='bank'),
        sa.Column('currency', sa.String(length=10), nullable=False),
        sa.Column('details', sa.JSON(), nullable=True),
        sa.Column('instructions', sa.Text(), nullable=True),
        sa.Column('qr_image', sa.String(length=255), nullable=True),
        sa.Column('help_image', sa.String(length=255), nullable=True),
        sa.Column('exchange_rate_to_usd', sa.Float(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_payment_method_name', 'payment_method', ['name'])
    op.create_index('ix_payment_method_type', 'payment_method', ['type'])
    op.create_index('ix_payment_method_is_active', 'payment_method', ['is_active'])
    op.create_index('ix_payment_method_sort_order', 'payment_method', ['sort_order'])
    op.create_index('ix_payment_method_created_at', 'payment_method', ['created_at'])


def downgrade():
    op.drop_index('ix_payment_method_created_at', table_name='payment_method')
    op.drop_index('ix_payment_method_sort_order', table_name='payment_method')
    op.drop_index('ix_payment_method_is_active', table_name='payment_method')
    op.drop_index('ix_payment_method_type', table_name='payment_method')
    op.drop_index('ix_payment_method_name', table_name='payment_method')
    op.drop_table('payment_method')
