"""
Insights over HM Land Registry Price Paid Data (PPD) yearly extracts, using polars.

Source: https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads
Data is Crown copyright / HM Land Registry, published under the Open Government
Licence v3.0 - attribute HM Land Registry if you publish anything derived from it.

Usage:
    .venv/bin/python analyze_price_paid.py [path/to/pp-2026.csv]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import polars as pl

COLUMNS = [
    "transaction_id",
    "price",
    "date_of_transfer",
    "postcode",
    "property_type",
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

PROPERTY_TYPE_LABELS = {
    "D": "Detached",
    "S": "Semi-detached",
    "T": "Terraced",
    "F": "Flat/Maisonette",
    "O": "Other",
}

# Minimum sample size before a group is trusted in "top/bottom by avg price"
# rankings, so a single £2m outlier in a tiny district doesn't skew results.
MIN_COUNT_COUNTY = 30
MIN_COUNT_DISTRICT = 15
MIN_COUNT_POSTCODE_AREA = 15

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
GBP_FORMATTER = mticker.FuncFormatter(lambda x, _: f"£{x:,.0f}")


def load_data(path: str) -> pl.LazyFrame:
    """Lazily load a PPD yearly CSV (no header row) with typed columns."""
    return (
        pl.scan_csv(path, has_header=False, new_columns=COLUMNS)
        .with_columns(
            pl.col("date_of_transfer").str.to_datetime("%Y-%m-%d %H:%M"),
            pl.col("postcode").str.extract(r"^(\S+)", 1).alias("postcode_area"),
            pl.col("property_type").replace(PROPERTY_TYPE_LABELS).alias("property_type_label"),
        )
    )


def core_stats(df: pl.DataFrame) -> dict:
    price = df["price"]
    dates = df["date_of_transfer"]
    return {
        "total_transactions": df.height,
        "date_range": [str(dates.min()), str(dates.max())],
        "price_min": price.min(),
        "price_max": price.max(),
        "price_mean": round(price.mean(), 2),
        "price_median": price.median(),
        "price_std": round(price.std(), 2),
    }


def by_property_type(df: pl.DataFrame) -> pl.DataFrame:
    return (
        df.group_by("property_type", "property_type_label")
        .agg(
            pl.len().alias("count"),
            pl.col("price").mean().round(2).alias("avg_price"),
            pl.col("price").median().alias("median_price"),
        )
        .sort("count", descending=True)
    )


def by_county(df: pl.DataFrame) -> dict:
    agg = (
        df.group_by("county")
        .agg(pl.len().alias("count"), pl.col("price").mean().round(2).alias("avg_price"))
        .filter(pl.col("count") >= MIN_COUNT_COUNTY)
    )
    return {
        "most_expensive": agg.sort("avg_price", descending=True).head(10),
        "least_expensive": agg.sort("avg_price").head(10),
    }


def by_district(df: pl.DataFrame) -> dict:
    agg = (
        df.group_by("district")
        .agg(pl.len().alias("count"), pl.col("price").mean().round(2).alias("avg_price"))
        .filter(pl.col("count") >= MIN_COUNT_DISTRICT)
    )
    return {
        "most_expensive": agg.sort("avg_price", descending=True).head(15),
        "least_expensive": agg.sort("avg_price").head(15),
    }


def freehold_vs_leasehold(df: pl.DataFrame) -> dict:
    overall = df.group_by("duration").agg(
        pl.len().alias("count"), pl.col("price").mean().round(2).alias("avg_price")
    )
    leasehold_share_by_type = (
        df.group_by("property_type_label")
        .agg(
            pl.len().alias("total"),
            (pl.col("duration") == "L").sum().alias("leasehold_count"),
        )
        .with_columns((pl.col("leasehold_count") / pl.col("total") * 100).round(1).alias("leasehold_pct"))
        .sort("leasehold_pct", descending=True)
    )
    return {"overall": overall, "leasehold_share_by_property_type": leasehold_share_by_type}


def monthly_trend(df: pl.DataFrame) -> pl.DataFrame:
    # Median is reported alongside the mean because a handful of multi-million-pound
    # 'Other'-type sales in any given month can swing the mean by tens of thousands of
    # pounds. Median is far more robust to those outliers and better reflects the
    # "typical" sale price trend month to month.
    monthly = (
        df.group_by(pl.col("date_of_transfer").dt.month().alias("month"))
        .agg(
            pl.len().alias("count"),
            pl.col("price").mean().round(2).alias("avg_price"),
            pl.col("price").median().alias("median_price"),
        )
        .sort("month")
    )
    return monthly.with_columns(
        (pl.col("avg_price").pct_change() * 100).round(2).alias("avg_price_mom_pct_change"),
        (pl.col("median_price").pct_change() * 100).round(2).alias("median_price_mom_pct_change"),
    )


def new_build_premium(df: pl.DataFrame) -> pl.DataFrame:
    result = df.group_by("property_type_label").agg(
        pl.col("price").filter(pl.col("new_build") == "Y").mean().round(2).alias("avg_price_new"),
        pl.col("price").filter(pl.col("new_build") == "N").mean().round(2).alias("avg_price_old"),
        (pl.col("new_build") == "Y").sum().alias("new_build_count"),
        (pl.col("new_build") == "N").sum().alias("existing_count"),
    )
    result = result.with_columns(
        ((pl.col("avg_price_new") - pl.col("avg_price_old")) / pl.col("avg_price_old") * 100)
        .round(1)
        .alias("new_build_premium_pct")
    ).sort("new_build_premium_pct", descending=True)
    return result


def outliers(df: pl.DataFrame) -> dict:
    cols = [
        "price",
        "date_of_transfer",
        "postcode",
        "property_type_label",
        "new_build",
        "duration",
        "town",
        "district",
        "county",
    ]
    most_expensive = df.select(cols).sort("price", descending=True).head(20)
    cheapest = df.select(cols).filter(pl.col("price") > 1000).sort("price").head(20)

    iqr = (
        df.with_columns(
            pl.col("price").quantile(0.25).over("property_type_label").alias("q1"),
            pl.col("price").quantile(0.75).over("property_type_label").alias("q3"),
        )
        .with_columns((pl.col("q3") - pl.col("q1")).alias("iqr"))
        .with_columns(
            (pl.col("q1") - 1.5 * pl.col("iqr")).alias("lower"),
            (pl.col("q3") + 1.5 * pl.col("iqr")).alias("upper"),
        )
        .with_columns(
            ((pl.col("price") < pl.col("lower")) | (pl.col("price") > pl.col("upper"))).alias("is_outlier")
        )
    )
    outlier_counts = (
        iqr.group_by("property_type_label")
        .agg(pl.len().alias("total"), pl.col("is_outlier").sum().alias("outlier_count"))
        .with_columns((pl.col("outlier_count") / pl.col("total") * 100).round(2).alias("outlier_pct"))
        .sort("outlier_pct", descending=True)
    )

    return {
        "most_expensive_sales": most_expensive,
        "cheapest_sales": cheapest,
        "iqr_outlier_counts_by_property_type": outlier_counts,
    }


def postcode_area_rollup(df: pl.DataFrame) -> dict:
    agg = (
        df.group_by("postcode_area")
        .agg(pl.len().alias("count"), pl.col("price").mean().round(2).alias("avg_price"))
        .filter(pl.col("count") >= MIN_COUNT_POSTCODE_AREA)
    )
    return {
        "most_expensive": agg.sort("avg_price", descending=True).head(15),
        "least_expensive": agg.sort("avg_price").head(15),
    }


def run_analysis(path: str) -> tuple[pl.DataFrame, dict]:
    df = load_data(path).collect(engine="streaming")

    insights = {
        "core_stats": core_stats(df),
        "by_property_type": by_property_type(df),
        "by_county": by_county(df),
        "by_district": by_district(df),
        "freehold_vs_leasehold": freehold_vs_leasehold(df),
        "monthly_trend": monthly_trend(df),
        "new_build_premium": new_build_premium(df),
        "outliers": outliers(df),
        "postcode_area_rollup": postcode_area_rollup(df),
    }
    return df, insights


def _print_section(title: str) -> None:
    print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")


def print_insights(insights: dict) -> None:
    pl.Config.set_tbl_rows(-1)
    pl.Config.set_tbl_cols(-1)
    pl.Config.set_fmt_str_lengths(40)

    _print_section("CORE STATS")
    for k, v in insights["core_stats"].items():
        print(f"  {k}: {v}")

    _print_section("BY PROPERTY TYPE")
    print(insights["by_property_type"])

    _print_section("BY COUNTY - MOST EXPENSIVE (avg, min n=%d)" % MIN_COUNT_COUNTY)
    print(insights["by_county"]["most_expensive"])
    _print_section("BY COUNTY - LEAST EXPENSIVE (avg, min n=%d)" % MIN_COUNT_COUNTY)
    print(insights["by_county"]["least_expensive"])

    _print_section("BY DISTRICT - MOST EXPENSIVE (avg, min n=%d)" % MIN_COUNT_DISTRICT)
    print(insights["by_district"]["most_expensive"])
    _print_section("BY DISTRICT - LEAST EXPENSIVE (avg, min n=%d)" % MIN_COUNT_DISTRICT)
    print(insights["by_district"]["least_expensive"])

    _print_section("FREEHOLD VS LEASEHOLD - OVERALL")
    print(insights["freehold_vs_leasehold"]["overall"])
    _print_section("LEASEHOLD SHARE BY PROPERTY TYPE")
    print(insights["freehold_vs_leasehold"]["leasehold_share_by_property_type"])

    _print_section("MONTHLY TREND")
    print(insights["monthly_trend"])

    _print_section("NEW BUILD PREMIUM BY PROPERTY TYPE")
    print(insights["new_build_premium"])

    _print_section("TOP 20 MOST EXPENSIVE SALES")
    print(insights["outliers"]["most_expensive_sales"])
    _print_section("TOP 20 CHEAPEST SALES (price > 1000)")
    print(insights["outliers"]["cheapest_sales"])
    _print_section("IQR OUTLIER RATE BY PROPERTY TYPE")
    print(insights["outliers"]["iqr_outlier_counts_by_property_type"])

    _print_section("POSTCODE AREA - MOST EXPENSIVE (avg, min n=%d)" % MIN_COUNT_POSTCODE_AREA)
    print(insights["postcode_area_rollup"]["most_expensive"])
    _print_section("POSTCODE AREA - LEAST EXPENSIVE (avg, min n=%d)" % MIN_COUNT_POSTCODE_AREA)
    print(insights["postcode_area_rollup"]["least_expensive"])


def save_insights(insights: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "core_stats": insights["core_stats"],
        "by_property_type": insights["by_property_type"].to_dicts(),
        "by_county_most_expensive": insights["by_county"]["most_expensive"].to_dicts(),
        "by_county_least_expensive": insights["by_county"]["least_expensive"].to_dicts(),
        "freehold_vs_leasehold_overall": insights["freehold_vs_leasehold"]["overall"].to_dicts(),
        "leasehold_share_by_property_type": insights["freehold_vs_leasehold"][
            "leasehold_share_by_property_type"
        ].to_dicts(),
        "monthly_trend": insights["monthly_trend"].to_dicts(),
        "new_build_premium": insights["new_build_premium"].to_dicts(),
        "iqr_outlier_counts_by_property_type": insights["outliers"][
            "iqr_outlier_counts_by_property_type"
        ].to_dicts(),
        "postcode_area_most_expensive": insights["postcode_area_rollup"]["most_expensive"].to_dicts(),
        "postcode_area_least_expensive": insights["postcode_area_rollup"]["least_expensive"].to_dicts(),
    }
    (out_dir / "pp_2026_insights.json").write_text(json.dumps(summary, indent=2, default=str))

    insights["by_district"]["most_expensive"].vstack(
        insights["by_district"]["least_expensive"]
    ).write_csv(out_dir / "insights_by_district.csv")

    insights["postcode_area_rollup"]["most_expensive"].vstack(
        insights["postcode_area_rollup"]["least_expensive"]
    ).write_csv(out_dir / "insights_postcode_area.csv")

    insights["outliers"]["most_expensive_sales"].vstack(
        insights["outliers"]["cheapest_sales"]
    ).write_csv(out_dir / "insights_outliers.csv")

    print(f"\nSaved: {out_dir / 'pp_2026_insights.json'}")
    print(f"Saved: {out_dir / 'insights_by_district.csv'}")
    print(f"Saved: {out_dir / 'insights_postcode_area.csv'}")
    print(f"Saved: {out_dir / 'insights_outliers.csv'}")


def _save_fig(fig, out_dir: Path, filename: str) -> None:
    fig.tight_layout()
    fig.savefig(out_dir / filename, dpi=150)
    plt.close(fig)
    print(f"Saved: {out_dir / filename}")


def plot_price_by_property_type(insights: dict, out_dir: Path) -> None:
    data = insights["by_property_type"].sort("avg_price")
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = ax.barh(data["property_type_label"], data["avg_price"], color="#4C72B0")
    for bar, count in zip(bars, data["count"]):
        ax.text(
            bar.get_width() + 5000,
            bar.get_y() + bar.get_height() / 2,
            f"n={count:,}",
            va="center",
            fontsize=9,
        )
    ax.set_title("Average Price Paid by Property Type (2026 YTD)")
    ax.set_xlabel("Average Price")
    ax.xaxis.set_major_formatter(GBP_FORMATTER)
    _save_fig(fig, out_dir, "chart_price_by_property_type.png")


def plot_price_distribution(df: pl.DataFrame, out_dir: Path) -> None:
    cap = df["price"].quantile(0.99)
    filtered = df.filter((pl.col("property_type") != "O") & (pl.col("price") <= cap))["price"]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(filtered.to_numpy(), bins=60, color="#55A868", edgecolor="white")
    ax.axvline(filtered.median(), color="#C44E52", linestyle="--", label=f"Median £{filtered.median():,.0f}")
    ax.axvline(filtered.mean(), color="#4C72B0", linestyle="--", label=f"Mean £{filtered.mean():,.0f}")
    ax.set_title("Price Distribution (excl. 'Other' type & top 1% by value)")
    ax.set_xlabel("Price")
    ax.set_ylabel("Number of Transactions")
    ax.xaxis.set_major_formatter(GBP_FORMATTER)
    ax.legend()
    _save_fig(fig, out_dir, "chart_price_distribution.png")


def plot_monthly_trend(monthly: pl.DataFrame, out_dir: Path) -> None:
    # Median price is used here (not mean) because a handful of extreme 'Other'-type
    # sales in a given month can swing the mean by tens of thousands of pounds and
    # create a misleading spike. Median reflects the typical sale price much more
    # reliably. See `monthly_trend()` for the underlying calculation.
    months = [MONTH_NAMES[m - 1] for m in monthly["month"]]
    fig, ax1 = plt.subplots(figsize=(8, 5))
    ax1.bar(months, monthly["count"], color="#B0C4DE", label="Transaction count")
    ax1.set_ylabel("Transaction count")
    ax1.set_xlabel("Month (2026)")

    ax2 = ax1.twinx()
    ax2.plot(
        months, monthly["median_price"], color="#C44E52", marker="o", linewidth=2, label="Median price"
    )
    ax2.set_ylabel("Median Price")
    ax2.yaxis.set_major_formatter(GBP_FORMATTER)
    for x, y in zip(months, monthly["median_price"]):
        ax2.annotate(f"£{y:,.0f}", (x, y), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=8)

    fig.legend(loc="upper right", bbox_to_anchor=(0.9, 0.95))
    ax1.set_title("Monthly Transaction Volume vs. Median Price (2026 YTD)")
    _save_fig(fig, out_dir, "chart_monthly_trend.png")


def plot_district_extremes(by_district: dict, out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(13, 6))

    most = by_district["most_expensive"].sort("avg_price")
    axes[0].barh(most["district"], most["avg_price"], color="#C44E52")
    axes[0].set_title(f"Most Expensive Districts (min n={MIN_COUNT_DISTRICT})")
    axes[0].xaxis.set_major_formatter(GBP_FORMATTER)
    axes[0].xaxis.set_major_locator(mticker.MaxNLocator(nbins=5))

    least = by_district["least_expensive"].sort("avg_price", descending=True)
    axes[1].barh(least["district"], least["avg_price"], color="#55A868")
    axes[1].set_title(f"Least Expensive Districts (min n={MIN_COUNT_DISTRICT})")
    axes[1].xaxis.set_major_formatter(GBP_FORMATTER)

    fig.suptitle("District Price Extremes - Average Price Paid (2026 YTD)")
    _save_fig(fig, out_dir, "chart_district_extremes.png")


def plot_freehold_leasehold(fl: dict, out_dir: Path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(11, 5))

    overall = fl["overall"]
    labels = ["Freehold" if d == "F" else "Leasehold" for d in overall["duration"]]
    axes[0].bar(labels, overall["avg_price"], color=["#4C72B0", "#DD8452"])
    axes[0].set_title("Average Price: Freehold vs Leasehold")
    axes[0].yaxis.set_major_formatter(GBP_FORMATTER)

    share = fl["leasehold_share_by_property_type"].sort("leasehold_pct")
    axes[1].barh(share["property_type_label"], share["leasehold_pct"], color="#DD8452")
    axes[1].set_title("Leasehold Share by Property Type")
    axes[1].set_xlabel("% Leasehold")
    axes[1].set_xlim(0, 100)

    _save_fig(fig, out_dir, "chart_freehold_leasehold.png")


def plot_new_build_premium(nb: pl.DataFrame, out_dir: Path) -> None:
    data = nb.sort("new_build_premium_pct")
    colors = ["#55A868" if v >= 0 else "#C44E52" for v in data["new_build_premium_pct"]]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.barh(data["property_type_label"], data["new_build_premium_pct"], color=colors)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title("New-Build Price Premium vs. Existing Stock, by Property Type")
    ax.set_xlabel("Premium (%)")
    _save_fig(fig, out_dir, "chart_new_build_premium.png")


def generate_charts(df: pl.DataFrame, insights: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")
    plot_price_by_property_type(insights, out_dir)
    plot_price_distribution(df, out_dir)
    plot_monthly_trend(insights["monthly_trend"], out_dir)
    plot_district_extremes(insights["by_district"], out_dir)
    plot_freehold_leasehold(insights["freehold_vs_leasehold"], out_dir)
    plot_new_build_premium(insights["new_build_premium"], out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze HM Land Registry Price Paid Data with polars.")
    parser.add_argument("path", nargs="?", default="pp-2026.csv", help="Path to the PPD yearly CSV file.")
    parser.add_argument(
        "--out-dir", default=".", help="Directory to write insight JSON/CSV files into (default: cwd)."
    )
    parser.add_argument(
        "--charts-dir", default="charts", help="Directory to write PNG charts into (default: ./charts)."
    )
    parser.add_argument("--no-charts", action="store_true", help="Skip generating charts.")
    args = parser.parse_args()

    df, insights = run_analysis(args.path)
    print_insights(insights)
    save_insights(insights, Path(args.out_dir))
    if not args.no_charts:
        generate_charts(df, insights, Path(args.charts_dir))


if __name__ == "__main__":
    main()
