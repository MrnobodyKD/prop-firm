"""add receiver trade, snapshot, and history order fields

Revision ID: d10000000005
Revises: d10000000004
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'd10000000005'
down_revision = 'd10000000004'
branch_labels = None
depends_on = None


def _snapshot_table(leverage_type=sa.Integer(), include_margin_level=False):
    from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table

    metadata = MetaData()
    table = Table(
        'account_snapshot', metadata,
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('challenge_purchase_id', sa.Integer(), nullable=False),
        sa.Column('timestamp', sa.DateTime(), nullable=True),
        sa.Column('ea_version', sa.String(length=20), nullable=True),
        sa.Column('terminal_build', sa.Integer(), nullable=True),
        sa.Column('mt5_login', sa.String(length=100), nullable=True),
        sa.Column('broker_server', sa.String(length=200), nullable=True),
        sa.Column('balance', sa.Float(), nullable=False),
        sa.Column('equity', sa.Float(), nullable=False),
        sa.Column('free_margin', sa.Float(), nullable=True),
        sa.Column('margin_used', sa.Float(), nullable=True),
        sa.Column('credit', sa.Float(), nullable=True),
        sa.Column('leverage', leverage_type, nullable=True),
        sa.Column('currency', sa.String(length=10), nullable=True),
        sa.Column('profit_from_start', sa.Float(), nullable=True),
        sa.Column('drawdown_from_peak', sa.Float(), nullable=True),
        sa.Column('open_positions_count', sa.Integer(), nullable=True),
        sa.Column('is_archived', sa.Boolean(), nullable=True),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        ForeignKeyConstraint(['challenge_purchase_id'], ['challenge_purchase.id']),
    )
    if include_margin_level:
        table.append_column(sa.Column('margin_level', sa.Float(), nullable=True))
    Index('ix_account_snapshot_challenge_purchase_id', table.c.challenge_purchase_id)
    Index('ix_account_snapshot_timestamp', table.c.timestamp)
    Index('ix_account_snapshot_mt5_login', table.c.mt5_login)
    Index('ix_account_snapshot_profit_from_start', table.c.profit_from_start)
    Index('ix_account_snapshot_drawdown_from_peak', table.c.drawdown_from_peak)
    Index('ix_account_snapshot_is_archived', table.c.is_archived)
    Index('idx_snapshot_challenge_timestamp', table.c.challenge_purchase_id, table.c.timestamp)
    Index('idx_snapshot_challenge_archived', table.c.challenge_purchase_id, table.c.is_archived)
    return table


def upgrade():
    with op.batch_alter_table('account_snapshot', copy_from=_snapshot_table()) as batch:
        batch.alter_column('leverage', existing_type=sa.Integer(), type_=sa.String(length=30), existing_nullable=True)
        batch.add_column(sa.Column('margin_level', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('ea_trade', sa.Column('swap', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('ea_trade', sa.Column('commission', sa.Float(), nullable=True, server_default='0.0'))
    op.add_column('ea_trade', sa.Column('comment', sa.String(length=200), nullable=True))
    if not sa.inspect(op.get_bind()).has_table('ea_order'):
        op.create_table(
            'ea_order',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('challenge_purchase_id', sa.Integer(), sa.ForeignKey('challenge_purchase.id'), nullable=False),
            sa.Column('ticket', sa.Integer(), nullable=False),
            sa.Column('position_id', sa.Integer(), nullable=True),
            sa.Column('symbol', sa.String(length=20), nullable=False),
            sa.Column('order_type', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('lots', sa.Float(), nullable=False, server_default='0.0'),
            sa.Column('price', sa.Float(), nullable=False, server_default='0.0'),
            sa.Column('sl', sa.Float(), nullable=False, server_default='0.0'),
            sa.Column('tp', sa.Float(), nullable=False, server_default='0.0'),
            sa.Column('state', sa.String(length=30), nullable=False, server_default=''),
            sa.Column('time_setup', sa.DateTime(timezone=True), nullable=False),
            sa.Column('time_done', sa.DateTime(timezone=True), nullable=True),
            sa.Column('comment', sa.String(length=200), nullable=True),
            sa.Column('magic', sa.Integer(), nullable=False, server_default='0'),
            sa.UniqueConstraint('challenge_purchase_id', 'ticket', name='unique_challenge_order_ticket'),
        )
        op.create_index('ix_ea_order_challenge_purchase_id', 'ea_order', ['challenge_purchase_id'])


def downgrade():
    leverage_values = op.get_bind().execute(
        sa.text('SELECT leverage FROM account_snapshot WHERE leverage IS NOT NULL')
    ).scalars()
    if any(not str(value).isdigit() for value in leverage_values):
        raise RuntimeError('Cannot downgrade non-integer leverage values; convert them before downgrading.')
    op.drop_index('ix_ea_order_challenge_purchase_id', table_name='ea_order')
    op.drop_table('ea_order')
    op.drop_column('ea_trade', 'comment')
    op.drop_column('ea_trade', 'commission')
    op.drop_column('ea_trade', 'swap')
    with op.batch_alter_table(
        'account_snapshot',
        copy_from=_snapshot_table(sa.String(length=30), include_margin_level=True),
    ) as batch:
        batch.drop_column('margin_level')
        batch.alter_column('leverage', existing_type=sa.String(length=30), type_=sa.Integer(), existing_nullable=True)
