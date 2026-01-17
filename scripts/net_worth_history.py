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
    """Reconstruct historical month-end balances for an account."""
    current_balance = account["balance"]

    txns_by_month = defaultdict(list)
    for txn in transactions:
        if txn["deleted"]:
            continue
        month = txn["date"][:7]
        txns_by_month[month].append(txn)

    if not txns_by_month:
        return {}

    months = sorted(txns_by_month.keys())
    first_month = months[0]

    start = datetime.strptime(first_month, "%Y-%m")
    end = datetime.now()
    all_months = []
    current = start
    while current <= end:
        all_months.append(current.strftime("%Y-%m"))
        current += relativedelta(months=1)

    balances = {}
    running_balance = current_balance

    for month in reversed(all_months):
        balances[month] = running_balance
        for txn in txns_by_month.get(month, []):
            running_balance -= txn["amount"]

    return balances


def generate_executive_summary(monthly_data: list, total_change: int,
                                pct_change: float, avg_monthly_change: int,
                                months_back: int) -> str:
    """Generate plain-English executive summary."""
    lines = []

    first_nw = milliunits_to_dollars(monthly_data[0]["net_worth"])
    last_nw = milliunits_to_dollars(monthly_data[-1]["net_worth"])
    change = milliunits_to_dollars(total_change)
    avg = milliunits_to_dollars(avg_monthly_change)

    # Overall trajectory
    if pct_change > 50:
        lines.append(
            f"Over the past {months_back} months, your net worth has grown from ${first_nw:,.0f} to "
            f"${last_nw:,.0f}—a gain of ${change:,.0f} ({pct_change:+.1f}%). That's serious progress."
        )
    elif pct_change > 20:
        lines.append(
            f"Net worth grew from ${first_nw:,.0f} to ${last_nw:,.0f} over {months_back} months, "
            f"up ${change:,.0f} ({pct_change:+.1f}%). Solid trajectory."
        )
    elif pct_change > 0:
        lines.append(
            f"You've added ${change:,.0f} to your net worth over {months_back} months ({pct_change:+.1f}%). "
            f"Positive, but not spectacular."
        )
    elif pct_change > -10:
        lines.append(
            f"Net worth is roughly flat over {months_back} months—${change:,.0f} change ({pct_change:+.1f}%). "
            f"You're treading water."
        )
    else:
        lines.append(
            f"Net worth declined from ${first_nw:,.0f} to ${last_nw:,.0f}, "
            f"down ${abs(change):,.0f} ({pct_change:.1f}%). Time to diagnose what went wrong."
        )

    # Monthly pace
    if avg > 0:
        lines.append(f"Average monthly gain: ${avg:,.0f}.")
    else:
        lines.append(f"Average monthly change: ${avg:,.0f}.")

    # Find best and worst months
    changes = []
    for i in range(1, len(monthly_data)):
        c = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
        changes.append((monthly_data[i]["month"], c))

    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])

        best_val = milliunits_to_dollars(best[1])
        worst_val = milliunits_to_dollars(worst[1])

        if best[1] > 0:
            lines.append(f"Best month: {best[0]} (+${best_val:,.0f}).")
        if worst[1] < 0:
            lines.append(f"Worst month: {worst[0]} (${worst_val:,.0f}).")

    # Liability trend
    first_liab = milliunits_to_dollars(monthly_data[0]["liabilities"])
    last_liab = milliunits_to_dollars(monthly_data[-1]["liabilities"])
    liab_change = last_liab - first_liab

    if liab_change < -5000:
        lines.append(f"Debt reduced by ${abs(liab_change):,.0f}—good work paying things down.")
    elif liab_change > 5000:
        lines.append(f"Debt increased by ${liab_change:,.0f}. Keep an eye on that.")

    return " ".join(lines)


def calculate_net_worth_history(months_back: int = 24) -> str:
    """Calculate net worth history for the last N months"""
    client = YNABClient()
    accounts = client.get_accounts()
    today = date.today()

    print("Fetching transaction history (this may take a moment)...")

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

    end_month = today.strftime("%Y-%m")
    start_date = today - relativedelta(months=months_back)
    start_month = start_date.strftime("%Y-%m")

    months = []
    current = start_date
    while current.strftime("%Y-%m") <= end_month:
        months.append(current.strftime("%Y-%m"))
        current += relativedelta(months=1)

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

    if len(monthly_data) >= 2:
        first = monthly_data[0]
        last = monthly_data[-1]
        total_change = last["net_worth"] - first["net_worth"]
        pct_change = (total_change / first["net_worth"] * 100) if first["net_worth"] != 0 else 0

        monthly_changes = []
        for i in range(1, len(monthly_data)):
            change = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
            monthly_changes.append(change)
        avg_monthly_change = sum(monthly_changes) // len(monthly_changes) if monthly_changes else 0
    else:
        total_change = 0
        pct_change = 0
        avg_monthly_change = 0

    exec_summary = generate_executive_summary(
        monthly_data, total_change, pct_change, avg_monthly_change, months_back
    )

    lines = [
        f"# Net Worth History",
        f"",
        f"**Period:** {start_month} to {end_month} ({months_back} months)",
        f"**Generated:** {today}",
        f"",
        f"## Executive Summary",
        f"",
        f"{exec_summary}",
        f"",
        f"## Key Metrics",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Starting Net Worth ({start_month}) | {format_currency(monthly_data[0]['net_worth'])} |",
        f"| Current Net Worth ({end_month}) | {format_currency(monthly_data[-1]['net_worth'])} |",
        f"| Total Change | {'+' if total_change >= 0 else ''}{format_currency(total_change)} |",
        f"| Percentage Change | {'+' if pct_change >= 0 else ''}{pct_change:.1f}% |",
        f"| Avg Monthly Change | {'+' if avg_monthly_change >= 0 else ''}{format_currency(avg_monthly_change)} |",
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

    lines.extend([
        f"",
        f"---",
        f"",
        f"*API calls: {client.cache_stats['misses']} fresh, {client.cache_stats['hits']} cached*",
    ])

    report_content = "\n".join(lines)

    md_path, html_path = save_report("net-worth-history", report_content)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Analyze net worth history")
    parser.add_argument("--months", "-m", type=int, default=24,
                        help="Number of months to analyze (default: 24)")
    args = parser.parse_args()

    calculate_net_worth_history(months_back=args.months)


if __name__ == "__main__":
    main()
