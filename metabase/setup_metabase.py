"""
One-shot Metabase setup for the Price Paid dashboard.

- Completes first-run admin setup (if needed)
- Adds the local Postgres price_paid database
- Creates native SQL Questions matching our insights
- Enables public sharing and writes URLs to frontend/src/config/metabaseCharts.ts

Usage (Metabase must already be running on :3000):
    .venv/bin/python metabase/setup_metabase.py
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:3000"
ADMIN_EMAIL = "admin@pricepaid.local"
ADMIN_PASSWORD = "PricePaidAdmin1!"
SITE_NAME = "Price Paid 2026"
CHARTS_TS = ROOT / "frontend" / "src" / "config" / "metabaseCharts.ts"

QUESTIONS = [
    {
        "id": "by-property-type",
        "name": "Average Price by Property Type",
        "description": "Mean sale price for each property type.",
        "display": "bar",
        "sql": """
SELECT property_type_label AS "Property Type",
       COUNT(*) AS "Count",
       ROUND(AVG(price)) AS "Avg Price"
FROM transactions
GROUP BY property_type_label
ORDER BY "Avg Price" ASC
""",
    },
    {
        "id": "price-distribution",
        "name": "Price Distribution",
        "description": "Sale price buckets excluding Other and top 1% approx (price <= 1.2M).",
        "display": "bar",
        "sql": """
SELECT FLOOR(price / 20000.0) * 20000 AS "Price Bucket",
       COUNT(*) AS "Transactions"
FROM transactions
WHERE property_type <> 'O' AND price <= 1200000
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "id": "monthly-trend",
        "name": "Monthly Volume vs Median Price",
        "description": "Transaction count and median price by month.",
        "display": "combo",
        "sql": """
SELECT EXTRACT(MONTH FROM date_of_transfer)::int AS "Month",
       COUNT(*) AS "Transactions",
       PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price) AS "Median Price"
FROM transactions
GROUP BY 1
ORDER BY 1
""",
    },
    {
        "id": "district-most-expensive",
        "name": "Most Expensive Districts",
        "description": "Top 15 districts by average price (min 15 sales, excl. Other property type).",
        "display": "row",
        "sql": """
SELECT district AS "District",
       ROUND(AVG(price)) AS "Avg Price"
FROM transactions
WHERE property_type <> 'O'
GROUP BY district
HAVING COUNT(*) >= 15
ORDER BY "Avg Price" DESC
LIMIT 15
""",
    },
    {
        "id": "district-least-expensive",
        "name": "Least Expensive Districts",
        "description": "Bottom 15 districts by average price (min 15 sales, excl. Other property type).",
        "display": "row",
        "sql": """
SELECT district AS "District",
       ROUND(AVG(price)) AS "Avg Price"
FROM transactions
WHERE property_type <> 'O'
GROUP BY district
HAVING COUNT(*) >= 15
ORDER BY "Avg Price" ASC
LIMIT 15
""",
    },
    {
        "id": "freehold-leasehold",
        "name": "Freehold vs Leasehold",
        "description": "Average price by tenure.",
        "display": "bar",
        "sql": """
SELECT CASE duration WHEN 'F' THEN 'Freehold' WHEN 'L' THEN 'Leasehold' ELSE duration END AS "Tenure",
       COUNT(*) AS "Count",
       ROUND(AVG(price)) AS "Avg Price"
FROM transactions
GROUP BY duration
ORDER BY "Tenure"
""",
    },
    {
        "id": "leasehold-share",
        "name": "Leasehold Share by Property Type",
        "description": "Percent of sales that are leasehold within each property type.",
        "display": "row",
        "sql": """
SELECT property_type_label AS "Property Type",
       COUNT(*) AS "Total",
       SUM(CASE WHEN duration = 'L' THEN 1 ELSE 0 END) AS "Leasehold Count",
       ROUND(100.0 * SUM(CASE WHEN duration = 'L' THEN 1 ELSE 0 END) / COUNT(*), 1) AS "Leasehold %"
FROM transactions
GROUP BY property_type_label
ORDER BY "Leasehold %" DESC
""",
    },
    {
        "id": "new-build-premium",
        "name": "New-Build Premium by Property Type",
        "description": "Percent premium of new builds vs existing stock.",
        "display": "row",
        "sql": """
SELECT property_type_label AS "Property Type",
       ROUND(AVG(price) FILTER (WHERE new_build = 'Y')) AS "Avg New",
       ROUND(AVG(price) FILTER (WHERE new_build = 'N')) AS "Avg Existing",
       ROUND(
         100.0 * (AVG(price) FILTER (WHERE new_build = 'Y') - AVG(price) FILTER (WHERE new_build = 'N'))
         / NULLIF(AVG(price) FILTER (WHERE new_build = 'N'), 0),
         1
       ) AS "Premium %"
FROM transactions
GROUP BY property_type_label
ORDER BY "Premium %" DESC NULLS LAST
""",
    },
]


def api(method: str, path: str, body: dict | None = None, session: str | None = None) -> dict | list | None:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if session:
        headers["X-Metabase-Session"] = session
    req = Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=120) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw)
    except HTTPError as e:
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> {e.code}: {err}") from e


def wait_healthy(timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urlopen(f"{BASE}/api/health", timeout=5) as resp:
                if resp.status == 200:
                    return
        except (URLError, HTTPError, TimeoutError):
            pass
        time.sleep(2)
    raise RuntimeError("Metabase health check timed out")


def ensure_setup() -> str:
    props = api("GET", "/api/session/properties")
    assert isinstance(props, dict)
    if props.get("has-user-setup"):
        print("Admin already set up; logging in...")
        sess = api(
            "POST",
            "/api/session",
            {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        )
        assert isinstance(sess, dict)
        return sess["id"]

    token = props.get("setup-token")
    if not token:
        raise RuntimeError("Setup required but no setup-token present")

    print("Running first-time Metabase setup...")
    result = api(
        "POST",
        "/api/setup",
        {
            "token": token,
            "user": {
                "first_name": "Admin",
                "last_name": "User",
                "email": ADMIN_EMAIL,
                "password": ADMIN_PASSWORD,
            },
            "prefs": {"site_name": SITE_NAME, "site_locale": "en"},
        },
    )
    assert isinstance(result, dict)
    # Newer Metabase returns session id under "id"
    if "id" in result:
        return result["id"]
    sess = api(
        "POST",
        "/api/session",
        {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert isinstance(sess, dict)
    return sess["id"]


def ensure_database(session: str) -> int:
    dbs = api("GET", "/api/database", session=session)
    assert isinstance(dbs, dict) or isinstance(dbs, list)
    items = dbs["data"] if isinstance(dbs, dict) and "data" in dbs else dbs
    for db in items:
        if db.get("name") == "Price Paid Postgres":
            print(f"Database already connected (id={db['id']})")
            # trigger sync
            api("POST", f"/api/database/{db['id']}/sync_schema", {}, session=session)
            return int(db["id"])

    print("Adding Postgres data source...")
    created = api(
        "POST",
        "/api/database",
        {
            "name": "Price Paid Postgres",
            "engine": "postgres",
            "details": {
                "host": "localhost",
                "port": 5433,
                "dbname": "price_paid",
                "user": Path.home().name,  # local trust auth uses OS user
                "password": "",
                "ssl": False,
            },
            "is_full_sync": True,
            "is_on_demand": False,
        },
        session=session,
    )
    assert isinstance(created, dict)
    db_id = int(created["id"])
    print(f"Created database id={db_id}; syncing schema...")
    api("POST", f"/api/database/{db_id}/sync_schema", {}, session=session)
    # give sync a moment
    time.sleep(3)
    return db_id


def enable_public_sharing(session: str) -> None:
    settings = api("GET", "/api/setting", session=session)
    # enable-public-sharing may already be on; set explicitly
    try:
        api("PUT", "/api/setting/enable-public-sharing", True, session=session)
    except RuntimeError:
        # some versions want {"value": true}
        api("PUT", "/api/setting/enable-public-sharing", {"value": True}, session=session)
    print("Public sharing enabled.")


def delete_existing_cards(session: str) -> None:
    names = {q["name"] for q in QUESTIONS}
    search = api("GET", "/api/search?models=card&q=Price", session=session)
    # Broader: list cards in root collection
    try:
        cards = api("GET", "/api/card", session=session)
    except RuntimeError:
        return
    if not isinstance(cards, list):
        return
    for card in cards:
        if card.get("name") in names:
            api("DELETE", f"/api/card/{card['id']}", session=session)
            print(f"Deleted existing card: {card['name']}")


def create_card(session: str, db_id: int, q: dict) -> tuple[int, str]:
    # Infer X/Y from the first two selected aliases when possible so Metabase
    # doesn't prompt "Which fields do you want to use for the X and Y axes?"
    viz: dict = {}
    if q["id"] == "monthly-trend":
        viz = {
            "graph.dimensions": ["Month"],
            "graph.metrics": ["Transactions", "Median Price"],
            "series_settings": {
                "Transactions": {"display": "bar"},
                "Median Price": {"display": "line", "axis": "right"},
            },
        }
    elif q["id"] == "price-distribution":
        viz = {
            "graph.dimensions": ["Price Bucket"],
            "graph.metrics": ["Transactions"],
            "graph.x_axis.title_text": "Price Bucket (£)",
            "graph.y_axis.title_text": "Transactions",
        }
    elif q["id"] == "by-property-type":
        viz = {
            "graph.dimensions": ["Property Type"],
            "graph.metrics": ["Avg Price"],
        }
    elif q["id"] in ("district-most-expensive", "district-least-expensive"):
        viz = {
            "graph.dimensions": ["District"],
            "graph.metrics": ["Avg Price"],
            "graph.max_categories": 20,
            "graph.other_category_percentage": 0,
        }
    elif q["id"] == "freehold-leasehold":
        viz = {
            "graph.dimensions": ["Tenure"],
            "graph.metrics": ["Avg Price"],
        }
    elif q["id"] == "leasehold-share":
        viz = {
            "graph.dimensions": ["Property Type"],
            "graph.metrics": ["Leasehold %"],
        }
    elif q["id"] == "new-build-premium":
        viz = {
            "graph.dimensions": ["Property Type"],
            "graph.metrics": ["Premium %"],
        }

    payload = {
        "name": q["name"],
        "description": q["description"],
        "display": q["display"],
        "visualization_settings": viz,
        "dataset_query": {
            "type": "native",
            "native": {"query": q["sql"].strip(), "template-tags": {}},
            "database": db_id,
        },
    }

    card = api("POST", "/api/card", payload, session=session)
    assert isinstance(card, dict)
    card_id = int(card["id"])

    # Enable public link
    public = api("POST", f"/api/card/{card_id}/public_link", {}, session=session)
    assert isinstance(public, dict)
    uuid = public.get("uuid") or public.get("public_uuid")
    if not uuid:
        # refetch card
        card = api("GET", f"/api/card/{card_id}", session=session)
        assert isinstance(card, dict)
        uuid = card.get("public_uuid")
    if not uuid:
        raise RuntimeError(f"No public uuid for card {card_id}")

    url = f"{BASE}/public/question/{uuid}"
    print(f"Created '{q['name']}' -> {url}")
    return card_id, url


def write_charts_config(urls: dict[str, str]) -> None:
    lines = [
        "/**",
        " * Metabase public embed URLs for each chart card.",
        " * Generated by metabase/setup_metabase.py — re-run that script to refresh.",
        " */",
        "export type MetabaseChart = {",
        "  id: string",
        "  title: string",
        "  description: string",
        "  url: string",
        "}",
        "",
        "export const METABASE_BASE_URL =",
        "  import.meta.env.VITE_METABASE_URL ?? 'http://localhost:3000'",
        "",
        "export const metabaseCharts: MetabaseChart[] = [",
    ]
    for q in QUESTIONS:
        url = urls[q["id"]]
        lines.append("  {")
        lines.append(f"    id: {json.dumps(q['id'])},")
        lines.append(f"    title: {json.dumps(q['name'])},")
        lines.append(f"    description: {json.dumps(q['description'])},")
        lines.append(f"    url: {json.dumps(url)},")
        lines.append("  },")
    lines.append("]")
    lines.append("")
    CHARTS_TS.write_text("\n".join(lines))
    print(f"Wrote {CHARTS_TS}")


def main() -> None:
    wait_healthy()
    session = ensure_setup()
    db_id = ensure_database(session)
    enable_public_sharing(session)
    delete_existing_cards(session)

    urls: dict[str, str] = {}
    for q in QUESTIONS:
        _, url = create_card(session, db_id, q)
        urls[q["id"]] = url

    write_charts_config(urls)
    print("Metabase setup complete.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
