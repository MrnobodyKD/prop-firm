"""Add per-phase trailing overall drawdown flags.

Revision ID: d10000000007
Revises: d10000000006
"""
from alembic import op
import sqlalchemy as sa


revision = 'd10000000007'
down_revision = 'd10000000006'
branch_labels = None
depends_on = None


def upgrade():
    for column in ('phase1_overall_dd_trailing', 'phase2_overall_dd_trailing',
                   'phase3_overall_dd_trailing', 'instant_overall_dd_trailing'):
        op.add_column('challenge_template', sa.Column(column, sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute("""UPDATE challenge_template SET
        phase1_overall_dd_trailing = CASE WHEN name ILIKE '%1 Step Trailing%' OR name ILIKE '%Pay After You Pass%' THEN TRUE ELSE FALSE END,
        phase2_overall_dd_trailing = CASE WHEN name ILIKE '%1 Step Trailing%' OR name ILIKE '%Pay After You Pass%' THEN TRUE ELSE FALSE END,
        phase3_overall_dd_trailing = CASE WHEN name ILIKE '%1 Step Trailing%' OR name ILIKE '%Pay After You Pass%' THEN TRUE ELSE FALSE END,
        instant_overall_dd_trailing = CASE WHEN name ILIKE '%1 Step Trailing%' OR name ILIKE '%Pay After You Pass%' THEN TRUE ELSE FALSE END""")


def downgrade():
    for column in ('instant_overall_dd_trailing', 'phase3_overall_dd_trailing',
                   'phase2_overall_dd_trailing', 'phase1_overall_dd_trailing'):
        op.drop_column('challenge_template', column)
