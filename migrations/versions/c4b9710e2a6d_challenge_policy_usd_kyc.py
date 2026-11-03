"""challenge policy USD and KYC schema update

Revision ID: c4b9710e2a6d
Revises: 7a0118b0b7fb
Create Date: 2026-11-03
"""
from alembic import op
import sqlalchemy as sa

revision = 'c4b9710e2a6d'
down_revision = '7a0118b0b7fb'
branch_labels = None
depends_on = None


def _columns(table):
    return {column['name'] for column in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    additions = {
        'challenge_template': [
            ('currency', sa.String(10)), ('no_expiry', sa.Boolean()),
            ('consistency_enabled', sa.Boolean()), ('max_single_day_profit_percent', sa.Float()),
            ('consistency_action', sa.String(20)), ('first_withdrawal_days', sa.Integer()),
            ('min_payout_percent', sa.Float()), ('performance_reward_percent', sa.Float()),
            ('performance_reward_mode', sa.String(30)), ('max_accounts_per_user', sa.Integer()),
            ('fee_refund_on_pass', sa.Boolean()), ('refund_policy_text', sa.Text()),
            ('banned_practices', sa.JSON()), ('news_trading_allowed', sa.Boolean()),
            ('overnight_trading_allowed', sa.Boolean()), ('ea_allowed', sa.Boolean()),
        ],
        'payout': [('crypto_address', sa.String(255))],
        'coupon': [('currency', sa.String(10))],
    }
    for table, fields in additions.items():
        present = _columns(table)
        with op.batch_alter_table(table) as batch:
            for name, column_type in fields:
                if name not in present:
                    batch.add_column(sa.Column(name, column_type, nullable=True))

    present = _columns('user')
    drops = [name for name in ('kyc_status', 'kyc_submitted_at', 'kyc_notes') if name in present]
    if drops:
        with op.batch_alter_table('user') as batch:
            for name in drops:
                batch.drop_column(name)


def downgrade():
    # KYC data is intentionally removed and cannot be restored on downgrade.
    with op.batch_alter_table('coupon') as batch:
        batch.drop_column('currency')
    with op.batch_alter_table('payout') as batch:
        batch.drop_column('crypto_address')
    with op.batch_alter_table('challenge_template') as batch:
        for name in ('currency', 'no_expiry', 'consistency_enabled', 'max_single_day_profit_percent',
                     'consistency_action', 'first_withdrawal_days', 'min_payout_percent',
                     'performance_reward_percent', 'performance_reward_mode', 'max_accounts_per_user',
                     'fee_refund_on_pass', 'refund_policy_text', 'banned_practices',
                     'news_trading_allowed', 'overnight_trading_allowed', 'ea_allowed'):
            batch.drop_column(name)
