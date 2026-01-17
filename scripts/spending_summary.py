#!/usr/bin/env python3
"""
Monthly Spending Summary - Shows spending by category vs budget
"""
import argparse
from collections import defaultdict
from datetime import date
from ynab_client import (
    YNABClient, format_currency, get_month_string,
    milliunits_to_dollars, save_report
)


def get_spending_summary(year: int = None, month: int = None) -> str:
    client = YNABClient()

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    month_str = get_month_string(year, month)
    month_label = f"{year}-{month:02d}"

    # Get month data which includes all categories with their budgeted/activity
    month_data = client.get_month(month_str)
    categories = month_data["categories"]

    # Group by category group
    groups = defaultdict(list)
    for cat in categories:
        if cat["deleted"] or cat["hidden"]:
            continue
        groups[cat["category_group_name"]].append(cat)

    # Skip internal categories
    skip_groups = ["Internal Master Category", "Credit Card Payments", "Hidden Categories"]

    # Build markdown report
    lines = [
        f"# Spending Summary - {month_label}",
        f"",
        f"Generated: {date.today()}",
        f"",
    ]

    total_budgeted = 0
    total_spent = 0

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
                elif pct > 80:
                    status = f"{pct:.0f}%"
                else:
                    status = f"{pct:.0f}%"
            else:
                status = "no budget"

            spent_str = f"${milliunits_to_dollars(spent):,.2f}"
            budgeted_str = f"${milliunits_to_dollars(budgeted):,.2f}"
            lines.append(f"| {cat['name']} | {spent_str} | {budgeted_str} | {status} |")

            total_budgeted += budgeted
            total_spent += spent

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

    # Save report
    filepath = save_report("spending", report_content, month_label)

    # Print to console
    print(report_content)
    print(f"\n---\nReport saved to: {filepath}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Monthly spending summary")
    parser.add_argument("--year", "-y", type=int, help="Year (default: current)")
    parser.add_argument("--month", "-m", type=int, help="Month (default: current)")
    args = parser.parse_args()

    get_spending_summary(args.year, args.month)


if __name__ == "__main__":
    main()
