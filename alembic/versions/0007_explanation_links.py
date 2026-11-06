"""Creator-selected transcript explanation links."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    if 'explanation_segments' not in {c['name'] for c in sa.inspect(op.get_bind()).get_columns('questions')}:
        op.add_column('questions', sa.Column('explanation_segments', sa.Text(), nullable=True))


def downgrade():
    raise RuntimeError('Trainly migrations are forward only; restore a backup to downgrade.')
