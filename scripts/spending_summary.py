#!/usr/bin/env python3
"""
Monthly Spending Summary - Shows spending by category vs budget
"""
import argparse
from collections import defaultdict
from datetime import date
from ynab_client import YNABClient, format_currency, get_month_string, milliunits_to_dollars


def get_spending_summary(year: int = None, month: int = None):
    client = YNABClient()
    month_str = get_month_string(year, month)

    # Get month data which includes all categories with their budgeted/activity
    month_data = client.get_month(month_str)
    categories = month_data["categories"]

    # Group by category group
    groups = defaultdict(list)
    for cat in categories:
        if cat["deleted"] or cat["hidden"]:
            continue
        groups[cat["category_group_name"]].append(cat)

    # Print summary
    print(f"\n{'='*60}")
    print(f"SPENDING SUMMARY - {month_str[:7]}")
    print(f"{'='*60}\n")

    total_budgeted = 0
    total_spent = 0

    # Skip internal categories
    skip_groups = ["Internal Master Category", "Credit Card Payments", "Hidden Categories"]

    for group_name, cats in sorted(groups.items()):
        if group_name in skip_groups:
            continue

        group_budgeted = sum(c["budgeted"] for c in cats)
        group_activity = sum(c["activity"] for c in cats)

        if group_budgeted == 0 and group_activity == 0:
            continue

        print(f"\n{group_name}")
        print("-" * 50)

        for cat in sorted(cats, key=lambda x: x["activity"]):
            budgeted = cat["budgeted"]
            activity = cat["activity"]  # Negative = spending
            balance = cat["balance"]

            if budgeted == 0 and activity == 0:
                continue

            spent = -activity  # Make positive for display
            pct = (spent / budgeted * 100) if budgeted > 0 else 0

            # Status indicator
            if budgeted > 0:
                if spent > budgeted:
                    status = "OVER"
                elif pct > 80:
                    status = "~80%"
                else:
                    status = ""
            else:
                status = "no budget"

            print(f"  {cat['name']:<25} {format_currency(-activity):>10} / {format_currency(budgeted):>10}  {status}")

            total_budgeted += budgeted
            total_spent += spent

        print(f"  {'Subtotal':<25} {format_currency(group_activity):>10} / {format_currency(group_budgeted):>10}")

    print(f"\n{'='*60}")
    print(f"  {'TOTAL SPENT':<25} {format_currency(int(total_spent)):>10} / {format_currency(total_budgeted):>10} budgeted")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(description="Monthly spending summary")
    parser.add_argument("--year", "-y", type=int, help="Year (default: current)")
    parser.add_argument("--month", "-m", type=int, help="Month (default: current)")
    args = parser.parse_args()

    get_spending_summary(args.year, args.month)


if __name__ == "__main__":
    main()
