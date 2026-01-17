#!/usr/bin/env python3
"""
Eating Out Tracker - Track spending against monthly hard cap
"""
import argparse
from datetime import date
from calendar import monthrange
from ynab_client import (
    YNABClient, format_currency, get_month_string,
    get_month_start_date, milliunits_to_dollars, save_report
)


def track_eating_out(year: int = None, month: int = None, show_transactions: bool = False) -> str:
    client = YNABClient()

    # Get config values
    eating_out_config = client.config["spending_caps"]["eating_out"]
    monthly_cap = eating_out_config["monthly_limit"]
    category_id = eating_out_config["category_id"]

    # Default to current month
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    month_str = get_month_string(year, month)
    month_label = f"{year}-{month:02d}"
    start_date = get_month_start_date(year, month)

    # Get category data for the month
    category = client.get_category_by_month(category_id, month_str)

    budgeted = milliunits_to_dollars(category["budgeted"])
    spent = -milliunits_to_dollars(category["activity"])
    balance = milliunits_to_dollars(category["balance"])

    # Calculate time metrics
    days_in_month = monthrange(year, month)[1]

    if year == today.year and month == today.month:
        days_elapsed = today.day
        days_remaining = days_in_month - days_elapsed
        is_current_month = True
    else:
        days_elapsed = days_in_month
        days_remaining = 0
        is_current_month = False

    # Calculate pace
    daily_avg = spent / days_elapsed if days_elapsed > 0 else 0
    projected_total = daily_avg * days_in_month
    remaining_budget = monthly_cap - spent
    daily_runway = remaining_budget / days_remaining if days_remaining > 0 else 0

    # Status determination
    if spent > monthly_cap:
        status = "OVER BUDGET"
    elif projected_total > monthly_cap:
        status = "WARNING - On pace to exceed"
    elif projected_total > monthly_cap * 0.8:
        status = "CAUTION - Approaching limit"
    else:
        status = "ON TRACK"

    # Build markdown report
    lines = [
        f"# Eating Out Tracker - {month_label}",
        f"",
        f"**Hard Cap:** ${monthly_cap:.2f}/month",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Spent this month | **${spent:.2f}** |",
        f"| Budget remaining | ${remaining_budget:.2f} |",
        f"| YNAB budgeted | ${budgeted:.2f} |",
    ]

    if budgeted < monthly_cap:
        lines.append(f"| Underfunded by | ${monthly_cap - budgeted:.2f} |")

    lines.extend([
        f"",
        f"## Pace",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Days elapsed | {days_elapsed} |",
        f"| Days remaining | {days_remaining} |",
        f"| Daily average | ${daily_avg:.2f}/day |",
        f"| Projected month-end | ${projected_total:.2f} |",
    ])

    if is_current_month and days_remaining > 0:
        lines.append(f"| **Daily runway** | **${daily_runway:.2f}/day** |")

    lines.extend([
        f"",
        f"## Status: {status}",
        f"",
    ])

    # Add transactions if requested
    if show_transactions:
        transactions = client.get_transactions(since_date=start_date)
        eating_out_txns = [
            t for t in transactions
            if t["category_id"] == category_id and not t["deleted"]
        ]

        lines.extend([
            f"## Transactions",
            f"",
            f"| Date | Payee | Amount |",
            f"|------|-------|--------|",
        ])

        for txn in sorted(eating_out_txns, key=lambda x: x["date"]):
            amount = -milliunits_to_dollars(txn["amount"])
            lines.append(f"| {txn['date']} | {txn['payee_name']} | ${amount:.2f} |")

        lines.extend([
            f"",
            f"**Total:** ${spent:.2f}",
        ])

    report_content = "\n".join(lines)

    # Save report
    filepath = save_report("eating-out", report_content, month_label)

    # Also print to console
    print(report_content)
    print(f"\n---\nReport saved to: {filepath}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Track eating out spending")
    parser.add_argument("--year", "-y", type=int, help="Year (default: current)")
    parser.add_argument("--month", "-m", type=int, help="Month (default: current)")
    parser.add_argument("--transactions", "-t", action="store_true",
                        help="Show individual transactions")
    args = parser.parse_args()

    track_eating_out(args.year, args.month, args.transactions)


if __name__ == "__main__":
    main()
