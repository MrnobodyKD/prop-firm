"""store challenge prices with cents

Revision ID: d10000000004
Revises: d10000000003
Create Date: 2026-11-09
"""
from alembic import op
import sqlalchemy as sa


revision = 'd10000000004'
down_revision = 'd10000000003'
branch_labels = None
depends_on = None


def _sqlite_alter_price(target_type, existing_type):
    from sqlalchemy import ForeignKeyConstraint, Index, MetaData, Table, UniqueConstraint, inspect

    bind = op.get_bind()
    inspector = inspect(bind)
    metadata = MetaData()
    columns = []
    for item in inspector.get_columns('challenge_template'):
        default = item.get('default')
        if default and default.startswith('(') and default.endswith(')'):
            inner = default[1:-1]
            if inner.isidentifier() and inner.lower() not in {'null', 'true', 'false', 'current_timestamp'}:
                default = "'" + inner.replace("'", "''") + "'"
        columns.append(sa.Column(
            item['name'],
            target_type if item['name'] == 'price' else item['type'],
            nullable=item['nullable'],
            primary_key=item.get('primary_key', False),
            server_default=sa.text(default) if default is not None else None,
        ))
    table = Table('challenge_template', metadata, *columns)
    for item in inspector.get_foreign_keys('challenge_template'):
        table.append_constraint(ForeignKeyConstraint(
            item['constrained_columns'],
            [f"{item['referred_table']}.{name}" for name in item['referred_columns']],
            name=item.get('name'),
        ))
    for item in inspector.get_unique_constraints('challenge_template'):
        table.append_constraint(UniqueConstraint(*item['column_names'], name=item.get('name')))
    for item in inspector.get_indexes('challenge_template'):
        Index(item['name'], *(table.c[name] for name in item['column_names']), unique=item.get('unique', False))
    with op.batch_alter_table('challenge_template', copy_from=table) as batch:
        batch.alter_column('price', existing_type=existing_type, type_=target_type, existing_nullable=False)


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'sqlite':
        _sqlite_alter_price(sa.Float(), sa.Integer())
    else:
        op.alter_column('challenge_template', 'price', existing_type=sa.Integer(), type_=sa.Float(), existing_nullable=False)


def downgrade():
    bind = op.get_bind()
    has_fractional_price = bind.execute(sa.text(
        'SELECT 1 FROM challenge_template WHERE price != CAST(price AS INTEGER) LIMIT 1'
    )).first()
    if has_fractional_price:
        raise RuntimeError('Cannot downgrade challenge prices while fractional prices exist; convert them before downgrading.')
    if bind.dialect.name == 'sqlite':
        _sqlite_alter_price(sa.Integer(), sa.Float())
    else:
        op.alter_column('challenge_template', 'price', existing_type=sa.Float(), type_=sa.Integer(), existing_nullable=False)
