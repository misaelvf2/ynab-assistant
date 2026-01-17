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


def generate_executive_summary(spent: float, monthly_cap: float, daily_avg: float,
                                projected_total: float, daily_runway: float,
                                days_remaining: int, budgeted: float,
                                is_current_month: bool) -> str:
    """Generate plain-English executive summary with curmudgeonly tone."""
    lines = []

    pct_used = (spent / monthly_cap * 100) if monthly_cap > 0 else 0
    pct_of_month = ((31 - days_remaining) / 31 * 100) if is_current_month else 100

    if spent > monthly_cap:
        lines.append(
            f"You've blown past your ${monthly_cap:.0f} cap, spending ${spent:.2f} on eating out. "
            f"The month isn't even over and you're already ${spent - monthly_cap:.2f} in the hole. "
            f"Time to cook at home."
        )
    elif projected_total > monthly_cap:
        lines.append(
            f"At your current pace of ${daily_avg:.2f}/day, you're on track to spend ${projected_total:.0f} "
            f"by month's end—that's ${projected_total - monthly_cap:.0f} over your ${monthly_cap:.0f} cap. "
            f"Rein it in."
        )
    elif projected_total > monthly_cap * 0.8:
        lines.append(
            f"You've spent ${spent:.2f} so far, which projects to ${projected_total:.0f} for the month. "
            f"That's cutting it close to your ${monthly_cap:.0f} limit. "
            f"You have ${daily_runway:.2f}/day to work with for the next {days_remaining} days—don't get reckless."
        )
    else:
        if spent < monthly_cap * 0.3 and pct_of_month > 40:
            lines.append(
                f"Only ${spent:.2f} spent with {days_remaining} days left—you're being unusually disciplined. "
                f"At ${daily_avg:.2f}/day, you'll finish around ${projected_total:.0f}, well under the ${monthly_cap:.0f} cap. "
                f"Don't let this go to your head."
            )
        else:
            lines.append(
                f"You've spent ${spent:.2f} on eating out, leaving ${monthly_cap - spent:.2f} for the remaining "
                f"{days_remaining} days. That's ${daily_runway:.2f}/day—manageable if you don't do anything stupid."
            )

    if budgeted < monthly_cap:
        lines.append(
            f"Note: You only budgeted ${budgeted:.0f} in YNAB but your hard cap is ${monthly_cap:.0f}. "
            f"Either fund it properly or admit the cap is aspirational."
        )

    return " ".join(lines)


def track_eating_out(year: int = None, month: int = None, show_transactions: bool = False) -> str:
    client = YNABClient()

    eating_out_config = client.config["spending_caps"]["eating_out"]
    monthly_cap = eating_out_config["monthly_limit"]
    category_id = eating_out_config["category_id"]

    today = date.today()
    if year is None:
        year = today.year
    if month is None:
        month = today.month

    month_str = get_month_string(year, month)
    month_label = f"{year}-{month:02d}"
    start_date = get_month_start_date(year, month)

    category = client.get_category_by_month(category_id, month_str)

    budgeted = milliunits_to_dollars(category["budgeted"])
    spent = -milliunits_to_dollars(category["activity"])

    days_in_month = monthrange(year, month)[1]

    if year == today.year and month == today.month:
        days_elapsed = today.day
        days_remaining = days_in_month - days_elapsed
        is_current_month = True
    else:
        days_elapsed = days_in_month
        days_remaining = 0
        is_current_month = False

    daily_avg = spent / days_elapsed if days_elapsed > 0 else 0
    projected_total = daily_avg * days_in_month
    remaining_budget = monthly_cap - spent
    daily_runway = remaining_budget / days_remaining if days_remaining > 0 else 0

    if spent > monthly_cap:
        status = "OVER BUDGET"
    elif projected_total > monthly_cap:
        status = "WARNING"
    elif projected_total > monthly_cap * 0.8:
        status = "CAUTION"
    else:
        status = "ON TRACK"

    # Generate executive summary
    exec_summary = generate_executive_summary(
        spent, monthly_cap, daily_avg, projected_total, daily_runway,
        days_remaining, budgeted, is_current_month
    )

    # Build markdown report
    lines = [
        f"# Eating Out Tracker - {month_label}",
        f"",
        f"**Hard Cap:** ${monthly_cap:.2f}/month | **Status:** {status}",
        f"",
        f"## Executive Summary",
        f"",
        f"{exec_summary}",
        f"",
        f"## Metrics",
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

    if show_transactions:
        transactions = client.get_transactions(since_date=start_date)
        eating_out_txns = [
            t for t in transactions
            if t["category_id"] == category_id and not t["deleted"]
        ]

        lines.extend([
            f"",
            f"## Transactions",
            f"",
            f"| Date | Payee | Amount |",
            f"|------|-------|--------|",
        ])

        for txn in sorted(eating_out_txns, key=lambda x: x["date"]):
            amount = -milliunits_to_dollars(txn["amount"])
            lines.append(f"| {txn['date']} | {txn['payee_name']} | ${amount:.2f} |")

        lines.append(f"")
        lines.append(f"**Total:** ${spent:.2f}")

    report_content = "\n".join(lines)

    md_path, html_path = save_report("eating-out", report_content, month_label)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

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
