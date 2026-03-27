#!/usr/bin/env python3
"""
Net Worth Calculator - Calculate total assets, liabilities, and net worth
"""
import argparse
import json
from datetime import date
from pathlib import Path
from ynab_assistant import (
    YNABClient, format_currency, milliunits_to_dollars,
    CACHE_DIR, save_report
)


SNAPSHOT_FILE = CACHE_DIR / "net_worth_snapshots.json"


def load_snapshots() -> dict:
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    return {}


def save_snapshot(snapshot_date: str, data: dict):
    snapshots = load_snapshots()
    snapshots[snapshot_date] = data
    SNAPSHOT_FILE.parent.mkdir(exist_ok=True)
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshots, f, indent=2)


def generate_executive_summary(net_worth: int, total_assets: int, total_liabilities: int,
                                total_on_budget: int, total_tracking: int,
                                total_credit: int, total_loans: int,
                                compare_data: dict = None) -> str:
    """Generate plain-English executive summary."""
    lines = []

    nw = milliunits_to_dollars(net_worth)
    assets = milliunits_to_dollars(total_assets)
    liabilities = milliunits_to_dollars(total_liabilities)
    liquid = milliunits_to_dollars(total_on_budget)
    investments = milliunits_to_dollars(total_tracking)
    cc_debt = milliunits_to_dollars(total_credit)
    loan_debt = milliunits_to_dollars(total_loans)

    # Overall position
    lines.append(f"Net worth stands at ${nw:,.0f}.")

    # Asset breakdown
    if investments > liquid:
        inv_pct = (investments / assets) * 100 if assets > 0 else 0
        lines.append(
            f"The bulk of your assets (${investments:,.0f}, {inv_pct:.0f}%) sit in investments and property, "
            f"with ${liquid:,.0f} in liquid accounts."
        )
    else:
        lines.append(f"You have ${liquid:,.0f} liquid and ${investments:,.0f} in investments/property.")

    # Debt assessment
    if liabilities > 0:
        debt_to_asset = (liabilities / assets) * 100 if assets > 0 else 0
        if cc_debt > 0 and loan_debt > 0:
            lines.append(
                f"Total debt is ${liabilities:,.0f} ({debt_to_asset:.0f}% of assets): "
                f"${cc_debt:,.0f} on credit cards and ${loan_debt:,.0f} in loans."
            )
        elif cc_debt > 0:
            lines.append(f"You're carrying ${cc_debt:,.0f} in credit card debt.")
        elif loan_debt > 0:
            lines.append(f"Loan debt totals ${loan_debt:,.0f}.")

    else:
        lines.append("No debt. Impressive, if true.")

    # Comparison if available
    if compare_data:
        prev_nw = compare_data["net_worth"]
        change = net_worth - prev_nw
        pct = (change / prev_nw * 100) if prev_nw != 0 else 0
        direction = "up" if change >= 0 else "down"
        lines.append(
            f"Compared to the snapshot, you're {direction} ${abs(milliunits_to_dollars(change)):,.0f} ({pct:+.1f}%)."
        )

    return " ".join(lines)


def calculate_net_worth(save: bool = False, compare: str = None) -> str:
    client = YNABClient()
    accounts = client.get_accounts()
    today = date.today()

    assets = {"on_budget": [], "tracking": []}
    liabilities = {"credit_cards": [], "loans": []}

    for acc in accounts:
        if acc["closed"] or acc["deleted"]:
            continue

        balance = acc["balance"]
        name = acc["name"]
        acc_type = acc["type"]

        entry = {"name": name, "balance": balance, "type": acc_type}

        if balance >= 0:
            if acc["on_budget"]:
                assets["on_budget"].append(entry)
            else:
                assets["tracking"].append(entry)
        else:
            if acc_type == "creditCard":
                liabilities["credit_cards"].append(entry)
            else:
                liabilities["loans"].append(entry)

    total_on_budget = sum(a["balance"] for a in assets["on_budget"])
    total_tracking = sum(a["balance"] for a in assets["tracking"])
    total_assets = total_on_budget + total_tracking

    total_credit = sum(abs(l["balance"]) for l in liabilities["credit_cards"])
    total_loans = sum(abs(l["balance"]) for l in liabilities["loans"])
    total_liabilities = total_credit + total_loans

    net_worth = total_assets - total_liabilities

    # Get comparison data if requested
    compare_data = None
    if compare:
        snapshots = load_snapshots()
        if compare in snapshots:
            compare_data = snapshots[compare]

    exec_summary = generate_executive_summary(
        net_worth, total_assets, total_liabilities,
        total_on_budget, total_tracking, total_credit, total_loans,
        compare_data
    )

    # Build markdown report
    lines = [
        f"# Net Worth Report - {today}",
        f"",
        f"## Executive Summary",
        f"",
        f"{exec_summary}",
        f"",
        f"## Assets",
        f"",
    ]

    if assets["on_budget"]:
        lines.extend([
            f"### On-Budget Accounts",
            f"",
            f"| Account | Balance |",
            f"|---------|---------|",
        ])
        for acc in sorted(assets["on_budget"], key=lambda x: -x["balance"]):
            lines.append(f"| {acc['name']} | {format_currency(acc['balance'])} |")
        lines.extend([
            f"| **Subtotal** | **{format_currency(total_on_budget)}** |",
            f"",
        ])

    if assets["tracking"]:
        lines.extend([
            f"### Tracking Accounts (Investments/Property)",
            f"",
            f"| Account | Balance |",
            f"|---------|---------|",
        ])
        for acc in sorted(assets["tracking"], key=lambda x: -x["balance"]):
            lines.append(f"| {acc['name']} | {format_currency(acc['balance'])} |")
        lines.extend([
            f"| **Subtotal** | **{format_currency(total_tracking)}** |",
            f"",
        ])

    lines.append(f"**Total Assets: {format_currency(total_assets)}**")
    lines.append(f"")

    lines.extend([
        f"## Liabilities",
        f"",
    ])

    if liabilities["credit_cards"]:
        lines.extend([
            f"### Credit Cards",
            f"",
            f"| Account | Balance |",
            f"|---------|---------|",
        ])
        for acc in sorted(liabilities["credit_cards"], key=lambda x: x["balance"]):
            lines.append(f"| {acc['name']} | {format_currency(abs(acc['balance']))} |")
        lines.extend([
            f"| **Subtotal** | **{format_currency(total_credit)}** |",
            f"",
        ])

    if liabilities["loans"]:
        lines.extend([
            f"### Loans",
            f"",
            f"| Account | Balance |",
            f"|---------|---------|",
        ])
        for acc in sorted(liabilities["loans"], key=lambda x: x["balance"]):
            lines.append(f"| {acc['name']} | {format_currency(abs(acc['balance']))} |")
        lines.extend([
            f"| **Subtotal** | **{format_currency(total_loans)}** |",
            f"",
        ])

    lines.extend([
        f"**Total Liabilities: {format_currency(total_liabilities)}**",
        f"",
        f"---",
        f"",
        f"# Net Worth: {format_currency(net_worth)}",
        f"",
    ])

    if compare and compare_data:
        prev_nw = compare_data["net_worth"]
        change = net_worth - prev_nw
        pct_change = (change / prev_nw * 100) if prev_nw != 0 else 0
        direction = "+" if change >= 0 else ""

        lines.extend([
            f"## Comparison to {compare}",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Previous | {format_currency(prev_nw)} |",
            f"| Current | {format_currency(net_worth)} |",
            f"| Change | {direction}{format_currency(change)} ({direction}{pct_change:.1f}%) |",
            f"",
        ])
    elif compare:
        lines.append(f"*No snapshot found for {compare}*")
        lines.append(f"")

    if save:
        today_str = str(today)
        snapshot_data = {
            "net_worth": net_worth,
            "total_assets": total_assets,
            "total_liabilities": total_liabilities,
            "on_budget_assets": total_on_budget,
            "tracking_assets": total_tracking,
            "credit_card_debt": total_credit,
            "loan_debt": total_loans
        }
        save_snapshot(today_str, snapshot_data)
        lines.append(f"*Snapshot saved for {today_str}*")

    report_content = "\n".join(lines)

    md_path, html_path = save_report("net-worth", report_content)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def list_snapshots():
    snapshots = load_snapshots()
    if snapshots:
        print("\nAvailable snapshots:")
        for date_str, data in sorted(snapshots.items()):
            print(f"  {date_str}: {format_currency(data['net_worth'])}")
    else:
        print("\nNo snapshots saved yet. Use --save to create one.")


def main():
    parser = argparse.ArgumentParser(description="Calculate net worth")
    parser.add_argument("--save", "-s", action="store_true",
                        help="Save today's snapshot for future comparison")
    parser.add_argument("--compare", "-c", type=str,
                        help="Compare to a previous snapshot date (YYYY-MM-DD)")
    parser.add_argument("--list-snapshots", "-l", action="store_true",
                        help="List available snapshots")
    args = parser.parse_args()

    if args.list_snapshots:
        list_snapshots()
        return

    calculate_net_worth(save=args.save, compare=args.compare)


if __name__ == "__main__":
    main()
