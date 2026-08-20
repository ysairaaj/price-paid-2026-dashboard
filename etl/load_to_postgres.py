"""
Load HM Land Registry Price Paid Data into PostgreSQL.

Reuses load_data() from analyze_price_paid.py, then COPY-loads into transactions.

Usage:
    .venv/bin/python etl/load_to_postgres.py [path/to/pp-2026.csv]
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import psycopg
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analyze_price_paid import load_data  # noqa: E402

DEFAULT_URL = "postgresql+psycopg://localhost:5433/price_paid"


def to_psycopg_dsn(url: str) -> str:
    """Convert SQLAlchemy URL to a plain psycopg connection string."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)

TABLE_COLUMNS = [
    "transaction_id",
    "price",
    "date_of_transfer",
    "postcode",
    "postcode_area",
    "property_type",
    "property_type_label",
    "new_build",
    "duration",
    "paon",
    "saon",
    "street",
    "locality",
    "town",
    "district",
    "county",
    "ppd_category",
    "record_status",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Load PPD CSV into PostgreSQL.")
    parser.add_argument("path", nargs="?", default=str(ROOT / "pp-2026.csv"))
    parser.add_argument("--db-url", default=DEFAULT_URL, help="Postgres URL")
    args = parser.parse_args()

    print(f"Loading {args.path}...")
    df = load_data(args.path).collect(engine="streaming").select(TABLE_COLUMNS)
    print(f"Loaded {df.height:,} rows. Writing to {args.db_url}...")

    engine = create_engine(args.db_url)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS transactions CASCADE"))
        conn.execute(
            text(
                """
                CREATE TABLE transactions (
                    transaction_id TEXT,
                    price BIGINT,
                    date_of_transfer TIMESTAMP,
                    postcode TEXT,
                    postcode_area TEXT,
                    property_type CHAR(1),
                    property_type_label TEXT,
                    new_build CHAR(1),
                    duration CHAR(1),
                    paon TEXT,
                    saon TEXT,
                    street TEXT,
                    locality TEXT,
                    town TEXT,
                    district TEXT,
                    county TEXT,
                    ppd_category CHAR(1),
                    record_status CHAR(1)
                )
                """
            )
        )

    # Fast path: stream CSV into COPY
    buf = io.BytesIO()
    df.write_csv(buf, include_header=False)
    buf.seek(0)

    dsn = to_psycopg_dsn(args.db_url)
    cols = ", ".join(TABLE_COLUMNS)
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            with cur.copy(f"COPY transactions ({cols}) FROM STDIN WITH (FORMAT csv)") as copy:
                while data := buf.read(1024 * 1024):
                    copy.write(data)
        conn.commit()

        with conn.cursor() as cur:
            for stmt in [
                "CREATE INDEX IF NOT EXISTS idx_transactions_property_type ON transactions (property_type)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_district ON transactions (district)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_county ON transactions (county)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions (date_of_transfer)",
                "CREATE INDEX IF NOT EXISTS idx_transactions_postcode_area ON transactions (postcode_area)",
            ]:
                cur.execute(stmt)
            cur.execute("SELECT COUNT(*) FROM transactions")
            count = cur.fetchone()[0]
        conn.commit()

    print(f"Done. transactions row count: {count:,}")


if __name__ == "__main__":
    main()
