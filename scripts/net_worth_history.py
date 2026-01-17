#!/usr/bin/env python3
"""
Net Worth History - Reconstruct and analyze historical net worth from transactions
"""
import argparse
from collections import defaultdict
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from ynab_client import (
    YNABClient, format_currency, milliunits_to_dollars, save_report
)


def reconstruct_account_history(account: dict, transactions: list) -> dict:
    """
    Reconstruct historical month-end balances for an account.
    Works backwards from current balance using transactions.

    Returns: {month_str: balance_milliunits}
    """
    current_balance = account["balance"]

    # Group transactions by month
    txns_by_month = defaultdict(list)
    for txn in transactions:
        if txn["deleted"]:
            continue
        month = txn["date"][:7]  # YYYY-MM
        txns_by_month[month].append(txn)

    # Get all months from first transaction to now
    if not txns_by_month:
        return {}

    months = sorted(txns_by_month.keys())
    first_month = months[0]

    # Generate all months from first to current
    start = datetime.strptime(first_month, "%Y-%m")
    end = datetime.now()
    all_months = []
    current = start
    while current <= end:
        all_months.append(current.strftime("%Y-%m"))
        current += relativedelta(months=1)

    # Work backwards from current balance
    balances = {}
    running_balance = current_balance

    for month in reversed(all_months):
        balances[month] = running_balance
        # Subtract transactions in this month (reverse them)
        for txn in txns_by_month.get(month, []):
            running_balance -= txn["amount"]

    return balances


def calculate_net_worth_history(months_back: int = 24) -> str:
    """Calculate net worth history for the last N months"""
    client = YNABClient()
    accounts = client.get_accounts()
    today = date.today()

    print("Fetching transaction history (this may take a moment)...")

    # Get transactions for all accounts
    all_account_histories = {}

    for acc in accounts:
        if acc["closed"] or acc["deleted"]:
            continue

        txns = client.get_account_transactions(acc["id"])
        history = reconstruct_account_history(acc, txns)
        if history:
            all_account_histories[acc["id"]] = {
                "name": acc["name"],
                "type": acc["type"],
                "on_budget": acc["on_budget"],
                "history": history
            }

    # Calculate net worth for each month
    # Determine date range
    end_month = today.strftime("%Y-%m")
    start_date = today - relativedelta(months=months_back)
    start_month = start_date.strftime("%Y-%m")

    # Generate month list
    months = []
    current = start_date
    while current.strftime("%Y-%m") <= end_month:
        months.append(current.strftime("%Y-%m"))
        current += relativedelta(months=1)

    # Calculate totals for each month
    monthly_data = []

    for month in months:
        assets = 0
        liabilities = 0

        for acc_id, acc_data in all_account_histories.items():
            balance = acc_data["history"].get(month, 0)

            if balance >= 0:
                assets += balance
            else:
                liabilities += abs(balance)

        net_worth = assets - liabilities
        monthly_data.append({
            "month": month,
            "assets": assets,
            "liabilities": liabilities,
            "net_worth": net_worth
        })

    # Calculate growth metrics
    if len(monthly_data) >= 2:
        first = monthly_data[0]
        last = monthly_data[-1]
        total_change = last["net_worth"] - first["net_worth"]
        pct_change = (total_change / first["net_worth"] * 100) if first["net_worth"] != 0 else 0

        # Monthly average change
        monthly_changes = []
        for i in range(1, len(monthly_data)):
            change = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
            monthly_changes.append(change)
        avg_monthly_change = sum(monthly_changes) / len(monthly_changes) if monthly_changes else 0
    else:
        total_change = 0
        pct_change = 0
        avg_monthly_change = 0

    # Build markdown report
    lines = [
        f"# Net Worth History",
        f"",
        f"**Period:** {start_month} to {end_month} ({months_back} months)",
        f"**Generated:** {today}",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Starting Net Worth ({start_month}) | {format_currency(monthly_data[0]['net_worth'])} |",
        f"| Current Net Worth ({end_month}) | {format_currency(monthly_data[-1]['net_worth'])} |",
        f"| Total Change | {'+' if total_change >= 0 else ''}{format_currency(total_change)} |",
        f"| Percentage Change | {'+' if pct_change >= 0 else ''}{pct_change:.1f}% |",
        f"| Avg Monthly Change | {'+' if avg_monthly_change >= 0 else ''}{format_currency(int(avg_monthly_change))} |",
        f"",
        f"## Monthly Breakdown",
        f"",
        f"| Month | Assets | Liabilities | Net Worth | Change |",
        f"|-------|--------|-------------|-----------|--------|",
    ]

    prev_nw = None
    for data in monthly_data:
        if prev_nw is not None:
            change = data["net_worth"] - prev_nw
            change_str = f"{'+' if change >= 0 else ''}{format_currency(change)}"
        else:
            change_str = "-"

        lines.append(
            f"| {data['month']} | {format_currency(data['assets'])} | "
            f"{format_currency(data['liabilities'])} | {format_currency(data['net_worth'])} | "
            f"{change_str} |"
        )
        prev_nw = data["net_worth"]

    # Add year-over-year comparison if we have enough data
    if len(monthly_data) >= 13:
        lines.extend([
            f"",
            f"## Year-over-Year",
            f"",
            f"| Month | This Year | Last Year | YoY Change |",
            f"|-------|-----------|-----------|------------|",
        ])

        for i in range(len(monthly_data) - 12, len(monthly_data)):
            if i >= 12:
                current = monthly_data[i]
                previous = monthly_data[i - 12]
                yoy_change = current["net_worth"] - previous["net_worth"]
                yoy_pct = (yoy_change / previous["net_worth"] * 100) if previous["net_worth"] != 0 else 0

                lines.append(
                    f"| {current['month']} | {format_currency(current['net_worth'])} | "
                    f"{format_currency(previous['net_worth'])} | "
                    f"{'+' if yoy_change >= 0 else ''}{format_currency(yoy_change)} ({'+' if yoy_pct >= 0 else ''}{yoy_pct:.1f}%) |"
                )

    # Cache stats
    lines.extend([
        f"",
        f"---",
        f"",
        f"*API calls: {client.cache_stats['misses']} fresh, {client.cache_stats['hits']} cached*",
    ])

    report_content = "\n".join(lines)

    # Save report
    filepath = save_report("net-worth-history", report_content)

    # Print to console
    print(report_content)
    print(f"\n---\nReport saved to: {filepath}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Analyze net worth history")
    parser.add_argument("--months", "-m", type=int, default=24,
                        help="Number of months to analyze (default: 24)")
    args = parser.parse_args()

    calculate_net_worth_history(months_back=args.months)


if __name__ == "__main__":
    main()
