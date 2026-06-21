"""Add market_exposure table (Market Health & Exposure dashboard).

One row per ``(date, market)`` holding the 0-100 recommended-exposure score
plus its inputs (distribution days, follow-through day, MA/trend, VIX, breadth).
Mirrors the ``market_breadth`` partitioning idiom. Additive — no backfill needed
beyond the optional historical run; the daily pipeline fills future rows.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260618_0022"
down_revision = "20260617_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = postgresql.JSONB if bind.dialect.name == "postgresql" else sa.JSON

    op.create_table(
        "market_exposure",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("market", sa.String(length=8), nullable=False, server_default="US"),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("exposure_score", sa.Float, nullable=False),
        sa.Column("stance", sa.String(length=32), nullable=False),
        sa.Column("benchmark_price", sa.Float),
        sa.Column("benchmark_ma50", sa.Float),
        sa.Column("benchmark_ma200", sa.Float),
        sa.Column("trend", sa.String(length=20)),
        sa.Column("distribution_day_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("follow_through_day", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("follow_through_date", sa.Date),
        sa.Column("vix", sa.Float),
        sa.Column("net_4pct", sa.Integer),
        sa.Column("components", json_type()),
        sa.Column("benchmark_symbol", sa.String(length=16)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("date", "market", name="uix_exposure_date_market"),
    )
    op.create_index("idx_exposure_date", "market_exposure", ["date"])
    op.create_index("idx_exposure_market_date", "market_exposure", ["market", "date"])


def downgrade() -> None:
    op.drop_index("idx_exposure_market_date", table_name="market_exposure")
    op.drop_index("idx_exposure_date", table_name="market_exposure")
    op.drop_table("market_exposure")
