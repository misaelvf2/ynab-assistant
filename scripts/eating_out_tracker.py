#!/usr/bin/env python3
"""
Eating Out Tracker - Track spending against monthly hard cap
"""
import argparse
from datetime import date, datetime
from calendar import monthrange
from ynab_client import (
    YNABClient, format_currency, get_month_string,
    get_month_start_date, milliunits_to_dollars
)


def track_eating_out(year: int = None, month: int = None, show_transactions: bool = False):
    client = YNABClient()

    # Get config values
    eating_out_config = client.config["spending_caps"]["eating_out"]
    monthly_cap = eating_out_config["monthly_limit"]  # in dollars
    category_id = eating_out_config["category_id"]
    category_name = eating_out_config["category_name"]

    # Default to current month
    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    month_str = get_month_string(year, month)
    start_date = get_month_start_date(year, month)

    # Get category data for the month
    category = client.get_category_by_month(category_id, month_str)

    budgeted = milliunits_to_dollars(category["budgeted"])
    spent = -milliunits_to_dollars(category["activity"])  # activity is negative
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
        status_color = "red"
    elif projected_total > monthly_cap:
        status = "WARNING - On pace to exceed"
        status_color = "yellow"
    elif projected_total > monthly_cap * 0.8:
        status = "CAUTION - Approaching limit"
        status_color = "yellow"
    else:
        status = "ON TRACK"
        status_color = "green"

    # Print report
    print(f"\n{'='*55}")
    print(f"  EATING OUT TRACKER - {month_str[:7]}")
    print(f"  Hard Cap: ${monthly_cap:.2f}/month")
    print(f"{'='*55}\n")

    print(f"  Spent this month:     ${spent:>8.2f}")
    print(f"  Budget remaining:     ${remaining_budget:>8.2f}")
    print(f"  YNAB budgeted:        ${budgeted:>8.2f}", end="")
    if budgeted < monthly_cap:
        print(f"  (underfunded by ${monthly_cap - budgeted:.2f}!)")
    else:
        print()

    print()
    print(f"  Days elapsed:         {days_elapsed:>8}")
    print(f"  Days remaining:       {days_remaining:>8}")

    print()
    print(f"  Daily average:        ${daily_avg:>8.2f}/day")
    print(f"  Projected month-end:  ${projected_total:>8.2f}")

    if is_current_month and days_remaining > 0:
        print()
        print(f"  >>> DAILY RUNWAY:     ${daily_runway:>8.2f}/day for {days_remaining} days <<<")

    print()
    print(f"  STATUS: {status}")
    print(f"{'='*55}")

    # Show transactions if requested
    if show_transactions:
        print(f"\n  Transactions:")
        print(f"  {'-'*50}")

        transactions = client.get_transactions(since_date=start_date)
        eating_out_txns = [
            t for t in transactions
            if t["category_id"] == category_id and not t["deleted"]
        ]

        for txn in sorted(eating_out_txns, key=lambda x: x["date"]):
            amount = -milliunits_to_dollars(txn["amount"])
            print(f"  {txn['date']}  {txn['payee_name']:<25}  ${amount:>7.2f}")

        print(f"  {'-'*50}")
        print(f"  Total: ${spent:.2f}")

    print()


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
