#!/usr/bin/env python3
"""
Monthly Spending Summary - Shows spending by category vs budget
"""
import argparse
from collections import defaultdict
from datetime import date
from ynab_assistant import (
    YNABClient, format_currency, get_month_string,
    milliunits_to_dollars, save_report, load_config
)


def generate_summary_block(categories_data: list, total_spent: int,
                           total_budgeted: int) -> str:
    """Generate structured summary data for the report."""
    lines = []

    spent_dollars = milliunits_to_dollars(total_spent)
    budgeted_dollars = milliunits_to_dollars(total_budgeted)
    pct_used = (total_spent / total_budgeted) * 100 if total_budgeted > 0 else 0

    if pct_used > 100:
        status = "OVER"
    elif pct_used > 85:
        status = "TIGHT"
    else:
        status = "UNDER"

    lines.append(f"- **Total Spent:** ${spent_dollars:,.0f} of ${budgeted_dollars:,.0f} budgeted ({pct_used:.0f}%)")
    lines.append(f"- **Status:** {status}")

    # Classify categories
    over_budget = []
    near_limit = []
    well_under = []

    for cat in categories_data:
        if cat["budgeted"] == 0:
            continue
        spent = -cat["activity"]
        pct = (spent / cat["budgeted"]) * 100 if cat["budgeted"] > 0 else 0

        if spent > cat["budgeted"]:
            over_amt = spent - cat["budgeted"]
            over_budget.append(f"{cat['name']} (${milliunits_to_dollars(over_amt):,.0f} over)")
        elif pct > 80:
            near_limit.append(f"{cat['name']} ({pct:.0f}%)")
        elif pct < 30 and cat["budgeted"] > 50000:
            well_under.append(f"{cat['name']} ({pct:.0f}%)")

    if over_budget:
        lines.append(f"- **Over budget:** {', '.join(over_budget[:5])}")
    if near_limit:
        lines.append(f"- **Near limit (>80%):** {', '.join(near_limit[:5])}")
    if well_under:
        lines.append(f"- **Well under (<30%):** {', '.join(well_under[:5])}")
    if not over_budget and not near_limit:
        lines.append("- **Flags:** None")

    return "\n".join(lines)


def get_spending_summary(year: int = None, month: int = None) -> str:
    client = YNABClient()

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    month_str = get_month_string(year, month)
    month_label = f"{year}-{month:02d}"

    month_data = client.get_month(month_str)
    categories = month_data["categories"]

    groups = defaultdict(list)
    for cat in categories:
        if cat["deleted"] or cat["hidden"]:
            continue
        groups[cat["category_group_name"]].append(cat)

    config = load_config()
    skip_groups = config.get("interpretation", {}).get(
        "skip_category_groups",
        ["Internal Master Category", "Credit Card Payments", "Hidden Categories"]
    )

    # Collect all categories for summary analysis
    all_cats = []
    total_budgeted = 0
    total_spent = 0

    for group_name, cats in groups.items():
        if group_name in skip_groups:
            continue
        for cat in cats:
            if cat["budgeted"] == 0 and cat["activity"] == 0:
                continue
            all_cats.append(cat)
            total_budgeted += cat["budgeted"]
            total_spent += -cat["activity"]

    summary_block = generate_summary_block(all_cats, total_spent, total_budgeted)

    # Build markdown report
    lines = [
        f"# Spending Summary - {month_label}",
        f"",
        f"Generated: {today}",
        f"",
        f"## Summary",
        f"",
        f"{summary_block}",
        f"",
    ]

    for group_name in sorted(groups.keys()):
        if group_name in skip_groups:
            continue

        cats = groups[group_name]
        group_budgeted = sum(c["budgeted"] for c in cats)
        group_activity = sum(c["activity"] for c in cats)

        if group_budgeted == 0 and group_activity == 0:
            continue

        lines.extend([
            f"## {group_name}",
            f"",
            f"| Category | Spent | Budgeted | Status |",
            f"|----------|-------|----------|--------|",
        ])

        for cat in sorted(cats, key=lambda x: x["activity"]):
            budgeted = cat["budgeted"]
            activity = cat["activity"]

            if budgeted == 0 and activity == 0:
                continue

            spent = -activity
            pct = (spent / budgeted * 100) if budgeted > 0 else 0

            if budgeted > 0:
                if spent > budgeted:
                    status = "OVER"
                else:
                    status = f"{pct:.0f}%"
            else:
                status = "no budget"

            spent_str = f"${milliunits_to_dollars(spent):,.2f}"
            budgeted_str = f"${milliunits_to_dollars(budgeted):,.2f}"
            lines.append(f"| {cat['name']} | {spent_str} | {budgeted_str} | {status} |")

        group_spent_str = f"${milliunits_to_dollars(-group_activity):,.2f}"
        group_budgeted_str = f"${milliunits_to_dollars(group_budgeted):,.2f}"
        lines.extend([
            f"| **Subtotal** | **{group_spent_str}** | **{group_budgeted_str}** | |",
            f"",
        ])

    lines.extend([
        f"---",
        f"",
        f"## Total",
        f"",
        f"| | Amount |",
        f"|--|--------|",
        f"| Total Spent | **${milliunits_to_dollars(total_spent):,.2f}** |",
        f"| Total Budgeted | ${milliunits_to_dollars(total_budgeted):,.2f} |",
    ])

    report_content = "\n".join(lines)

    md_path, html_path = save_report("spending", report_content, month_label)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Monthly spending summary")
    parser.add_argument("--year", "-y", type=int, help="Year (default: current)")
    parser.add_argument("--month", "-m", type=int, help="Month (default: current)")
    args = parser.parse_args()

    get_spending_summary(args.year, args.month)


if __name__ == "__main__":
    main()
