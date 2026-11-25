"""Add coupon-attributed affiliate applications and payout cycles.

NOTE: do not run `flask db upgrade` on the live server until the owner resolves migration 49a9c5c44b75 (known-destructive, drops user columns). This file only adds new tables.
"""
from alembic import op
import sqlalchemy as sa

revision = 'adccbd3c01e3'
down_revision = '49a9c5c44b75'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('affiliate_applications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('full_name', sa.String(length=150), nullable=False),
        sa.Column('social_handle', sa.String(length=200), nullable=True),
        sa.Column('phone', sa.String(length=20), nullable=False),
        sa.Column('contact_email', sa.String(length=120), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=True),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_affiliate_applications_user_id', 'affiliate_applications', ['user_id'])
    op.create_index('ix_affiliate_applications_status', 'affiliate_applications', ['status'])
    op.create_table('affiliates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('commission_percent', sa.Float(), server_default='15.0', nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=True),
        sa.Column('source', sa.String(length=20), server_default='applied', nullable=True),
        sa.Column('application_id', sa.Integer(), nullable=True),
        sa.Column('payout_method', sa.String(length=30), nullable=True),
        sa.Column('payout_details', sa.String(length=200), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['application_id'], ['affiliate_applications.id']),
        sa.ForeignKeyConstraint(['approved_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['user_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_affiliates_user_id', 'affiliates', ['user_id'], unique=True)
    op.create_index('ix_affiliates_is_active', 'affiliates', ['is_active'])
    op.create_table('affiliate_coupons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('coupon_id', sa.Integer(), nullable=False),
        sa.Column('added_by_id', sa.Integer(), nullable=True),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['added_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id']),
        sa.ForeignKeyConstraint(['coupon_id'], ['coupon.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('affiliate_id', 'coupon_id', name='uq_affiliate_coupon'),
        sa.UniqueConstraint('coupon_id', name='uq_coupon_single_affiliate'))
    op.create_index('ix_affiliate_coupons_affiliate_id', 'affiliate_coupons', ['affiliate_id'])
    op.create_index('ix_affiliate_coupons_coupon_id', 'affiliate_coupons', ['coupon_id'])
    op.create_table('affiliate_payouts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('affiliate_id', sa.Integer(), nullable=False),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('total_sales', sa.Float(), nullable=True),
        sa.Column('total_commission', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='open', nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejected_reason', sa.Text(), nullable=True),
        sa.Column('rejected_by_id', sa.Integer(), nullable=True),
        sa.Column('paid_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('paid_by_id', sa.Integer(), nullable=True),
        sa.Column('payment_reference', sa.String(length=200), nullable=True),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['affiliate_id'], ['affiliates.id']),
        sa.ForeignKeyConstraint(['paid_by_id'], ['user.id']),
        sa.ForeignKeyConstraint(['rejected_by_id'], ['user.id']),
        sa.PrimaryKeyConstraint('id'))
    op.create_index('ix_affiliate_payouts_affiliate_id', 'affiliate_payouts', ['affiliate_id'])
    op.create_index('ix_affiliate_payouts_status', 'affiliate_payouts', ['status'])


def downgrade():
    op.drop_index('ix_affiliate_payouts_status', table_name='affiliate_payouts')
    op.drop_index('ix_affiliate_payouts_affiliate_id', table_name='affiliate_payouts')
    op.drop_table('affiliate_payouts')
    op.drop_index('ix_affiliate_coupons_coupon_id', table_name='affiliate_coupons')
    op.drop_index('ix_affiliate_coupons_affiliate_id', table_name='affiliate_coupons')
    op.drop_table('affiliate_coupons')
    op.drop_index('ix_affiliates_is_active', table_name='affiliates')
    op.drop_index('ix_affiliates_user_id', table_name='affiliates')
    op.drop_table('affiliates')
    op.drop_index('ix_affiliate_applications_status', table_name='affiliate_applications')
    op.drop_index('ix_affiliate_applications_user_id', table_name='affiliate_applications')
    op.drop_table('affiliate_applications')
