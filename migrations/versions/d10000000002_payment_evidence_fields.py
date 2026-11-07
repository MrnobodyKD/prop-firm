"""add payment rail and evidence fields

Revision ID: d10000000002
Revises: d10000000001
Create Date: 2026-11-07
"""
from alembic import op
import sqlalchemy as sa

revision = 'd10000000002'
down_revision = 'd10000000001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('payment') as batch:
        batch.add_column(sa.Column('payment_method_type', sa.String(length=30), nullable=True))
        batch.add_column(sa.Column('payment_method_id', sa.Integer(), nullable=True))
        batch.add_column(sa.Column('method_name', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('external_reference', sa.String(length=160), nullable=True))
        batch.add_column(sa.Column('receipt_url', sa.String(length=500), nullable=True))
        batch.add_column(sa.Column('evidence_path', sa.String(length=255), nullable=True))
        batch.add_column(sa.Column('amount_local', sa.Float(), nullable=True))
        batch.add_column(sa.Column('local_currency', sa.String(length=10), nullable=True))
        batch.add_column(sa.Column('invoice_url', sa.String(length=1000), nullable=True))
        batch.add_column(sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
        batch.create_foreign_key('fk_payment_payment_method_id', 'payment_method', ['payment_method_id'], ['id'])

    op.create_index('ix_payment_payment_method_type', 'payment', ['payment_method_type'])
    op.create_index('ix_payment_payment_method_id', 'payment', ['payment_method_id'])
    op.create_index('ix_payment_external_reference', 'payment', ['external_reference'])
    op.create_index('ix_payment_expires_at', 'payment', ['expires_at'])


def downgrade():
    op.drop_index('ix_payment_expires_at', table_name='payment')
    op.drop_index('ix_payment_external_reference', table_name='payment')
    op.drop_index('ix_payment_payment_method_id', table_name='payment')
    op.drop_index('ix_payment_payment_method_type', table_name='payment')
    with op.batch_alter_table('payment') as batch:
        batch.drop_constraint('fk_payment_payment_method_id', type_='foreignkey')
        batch.drop_column('expires_at')
        batch.drop_column('invoice_url')
        batch.drop_column('local_currency')
        batch.drop_column('amount_local')
        batch.drop_column('evidence_path')
        batch.drop_column('receipt_url')
        batch.drop_column('external_reference')
        batch.drop_column('method_name')
        batch.drop_column('payment_method_id')
        batch.drop_column('payment_method_type')
