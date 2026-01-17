#!/usr/bin/env python3
"""
Net Worth Calculator - Calculate total assets, liabilities, and net worth
Optionally compare to previous snapshot for growth tracking
"""
import argparse
import json
from datetime import date, datetime
from pathlib import Path
from ynab_client import YNABClient, format_currency, milliunits_to_dollars, CACHE_DIR


SNAPSHOT_FILE = CACHE_DIR / "net_worth_snapshots.json"


def load_snapshots() -> dict:
    """Load historical snapshots"""
    if SNAPSHOT_FILE.exists():
        with open(SNAPSHOT_FILE) as f:
            return json.load(f)
    return {}


def save_snapshot(snapshot_date: str, data: dict):
    """Save a snapshot"""
    snapshots = load_snapshots()
    snapshots[snapshot_date] = data
    SNAPSHOT_FILE.parent.mkdir(exist_ok=True)
    with open(SNAPSHOT_FILE, "w") as f:
        json.dump(snapshots, f, indent=2)


def calculate_net_worth(save: bool = False, compare: str = None):
    client = YNABClient()
    accounts = client.get_accounts()

    # Categorize accounts
    assets = {"on_budget": [], "tracking": []}
    liabilities = {"credit_cards": [], "loans": []}

    for acc in accounts:
        if acc["closed"] or acc["deleted"]:
            continue

        balance = acc["balance"]  # milliunits
        name = acc["name"]
        acc_type = acc["type"]

        entry = {
            "name": name,
            "balance": balance,
            "type": acc_type
        }

        if balance >= 0:
            # Asset
            if acc["on_budget"]:
                assets["on_budget"].append(entry)
            else:
                assets["tracking"].append(entry)
        else:
            # Liability (negative balance)
            if acc_type == "creditCard":
                liabilities["credit_cards"].append(entry)
            else:
                liabilities["loans"].append(entry)

    # Calculate totals
    total_on_budget = sum(a["balance"] for a in assets["on_budget"])
    total_tracking = sum(a["balance"] for a in assets["tracking"])
    total_assets = total_on_budget + total_tracking

    total_credit = sum(abs(l["balance"]) for l in liabilities["credit_cards"])
    total_loans = sum(abs(l["balance"]) for l in liabilities["loans"])
    total_liabilities = total_credit + total_loans

    net_worth = total_assets - total_liabilities

    # Print report
    print(f"\n{'='*60}")
    print(f"  NET WORTH REPORT - {date.today()}")
    print(f"{'='*60}")

    print(f"\n  ASSETS")
    print(f"  {'-'*55}")

    if assets["on_budget"]:
        print(f"\n  On-Budget Accounts:")
        for acc in sorted(assets["on_budget"], key=lambda x: -x["balance"]):
            print(f"    {acc['name']:<30} {format_currency(acc['balance']):>12}")
        print(f"    {'Subtotal':<30} {format_currency(total_on_budget):>12}")

    if assets["tracking"]:
        print(f"\n  Tracking Accounts (Investments/Property):")
        for acc in sorted(assets["tracking"], key=lambda x: -x["balance"]):
            print(f"    {acc['name']:<30} {format_currency(acc['balance']):>12}")
        print(f"    {'Subtotal':<30} {format_currency(total_tracking):>12}")

    print(f"\n  {'TOTAL ASSETS':<32} {format_currency(total_assets):>12}")

    print(f"\n  LIABILITIES")
    print(f"  {'-'*55}")

    if liabilities["credit_cards"]:
        print(f"\n  Credit Cards:")
        for acc in sorted(liabilities["credit_cards"], key=lambda x: x["balance"]):
            print(f"    {acc['name']:<30} {format_currency(abs(acc['balance'])):>12}")
        print(f"    {'Subtotal':<30} {format_currency(total_credit):>12}")

    if liabilities["loans"]:
        print(f"\n  Loans:")
        for acc in sorted(liabilities["loans"], key=lambda x: x["balance"]):
            print(f"    {acc['name']:<30} {format_currency(abs(acc['balance'])):>12}")
        print(f"    {'Subtotal':<30} {format_currency(total_loans):>12}")

    print(f"\n  {'TOTAL LIABILITIES':<32} {format_currency(total_liabilities):>12}")

    print(f"\n{'='*60}")
    print(f"  {'NET WORTH':<32} {format_currency(net_worth):>12}")
    print(f"{'='*60}")

    # Compare to previous snapshot if requested
    if compare:
        snapshots = load_snapshots()
        if compare in snapshots:
            prev = snapshots[compare]
            prev_nw = prev["net_worth"]
            change = net_worth - prev_nw
            pct_change = (change / prev_nw * 100) if prev_nw != 0 else 0
            direction = "+" if change >= 0 else ""

            print(f"\n  Comparison to {compare}:")
            print(f"    Previous:  {format_currency(prev_nw)}")
            print(f"    Current:   {format_currency(net_worth)}")
            print(f"    Change:    {direction}{format_currency(change)} ({direction}{pct_change:.1f}%)")
        else:
            print(f"\n  No snapshot found for {compare}")
            print(f"  Available snapshots: {list(snapshots.keys())}")

    # Save snapshot if requested
    if save:
        today_str = str(date.today())
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
        print(f"\n  Snapshot saved for {today_str}")

    print()

    return {
        "net_worth": net_worth,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities
    }


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
        snapshots = load_snapshots()
        if snapshots:
            print("\nAvailable snapshots:")
            for date_str, data in sorted(snapshots.items()):
                print(f"  {date_str}: {format_currency(data['net_worth'])}")
        else:
            print("\nNo snapshots saved yet. Use --save to create one.")
        return

    calculate_net_worth(save=args.save, compare=args.compare)


if __name__ == "__main__":
    main()
