"""Add expression indexes for feature-store preset filter fields.

The scan results endpoint filters/sorts ``stock_feature_daily`` rows on
screening fields that live inside the ``details_json`` blob (rs_rating,
minervini_score, stage, ...). Only ``composite_score`` / ``overall_rating``
were real indexed columns, so any preset that filtered a JSON field forced a
full scan that read every row's large ``details_json`` blob to evaluate the
``CAST(details_json ->> 'field' AS FLOAT)`` predicate. On the live US daily
run (~10k rows) that took >35s and tripped the 30s client timeout, so presets
appeared not to filter.

The query builder emits exactly ``CAST(details_json ->> '<field>' AS FLOAT)``
for these range filters (and always constrains ``run_id``). A composite
expression index ``(run_id, (CAST(details_json ->> '<field>' AS FLOAT)))``
matches that predicate, so the planner resolves the filter in the index
instead of reading every blob — verified via EXPLAIN to switch the plan from
a heap scan to a ``Bitmap Index Scan``.

No write-path or backfill change is needed: the index covers existing rows on
build and future rows on upsert. Postgres-only (the app requires PostgreSQL;
the unit-test harness builds the schema via metadata, not migrations).
"""

from __future__ import annotations

from alembic import op

revision = "20260617_0021"
down_revision = "20260601_0020"
branch_labels = None
depends_on = None

# Hot preset filter/sort fields stored in details_json. Each is filtered via
# FilterSpec.add_range -> json_number -> CAST(details_json ->> 'f' AS FLOAT).
# rs_rating is the workhorse (nearly every preset constrains it); the rest seed
# the bitmap for score / growth / pattern / mover presets. Booleans and
# pattern-string fields are intentionally omitted — they co-occur with one of
# these and filter cheaply on the already-narrowed heap set.
_FIELDS = [
    "rs_rating",
    "minervini_score",
    "canslim_score",
    "stage",
    "eps_growth_qq",
    "se_setup_score",
    "volume_breakthrough_score",
    "ipo_score",
    "perf_week",
    "price_change_1d",
]


def _index_name(field: str) -> str:
    return f"ix_sfd_run_{field}"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for field in _FIELDS:
        op.execute(
            f'CREATE INDEX IF NOT EXISTS {_index_name(field)} '
            f'ON stock_feature_daily '
            f"(run_id, (CAST(details_json ->> '{field}' AS FLOAT)))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for field in _FIELDS:
        op.execute(f"DROP INDEX IF EXISTS {_index_name(field)}")
