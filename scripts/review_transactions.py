#!/usr/bin/env python3
"""
Transaction Review Flags - Surface transactions that need attention
"""
import argparse
from collections import defaultdict
from datetime import date, timedelta
from ynab_client import (
    YNABClient, format_currency, milliunits_to_dollars, get_month_start_date
)


def review_transactions(days: int = 30, memo_threshold: float = 100):
    client = YNABClient()

    # Get transactions from the last N days
    since = date.today() - timedelta(days=days)
    since_str = since.strftime("%Y-%m-%d")

    transactions = client.get_transactions(since_date=since_str)

    # Filter out deleted and transfer transactions
    txns = [
        t for t in transactions
        if not t["deleted"] and t["transfer_account_id"] is None
    ]

    # Track issues
    uncategorized = []
    missing_memo = []
    unapproved = []
    payee_variations = defaultdict(list)

    memo_threshold_mu = int(memo_threshold * 1000)

    for txn in txns:
        amount = txn["amount"]
        abs_amount = abs(amount)

        # Check for uncategorized
        if txn["category_name"] == "Uncategorized" or txn["category_id"] is None:
            # Skip inflows that might legitimately be uncategorized
            if amount < 0:  # Outflow
                uncategorized.append(txn)

        # Check for missing memo on large transactions
        if abs_amount >= memo_threshold_mu and not txn["memo"]:
            missing_memo.append(txn)

        # Check for unapproved
        if not txn["approved"]:
            unapproved.append(txn)

        # Track payee name variations
        if txn["import_payee_name"] and txn["payee_name"]:
            import_name = txn["import_payee_name"].lower().strip()
            clean_name = txn["payee_name"]
            payee_variations[clean_name].append(import_name)

    # Find payees with multiple import variations (possible categorization issues)
    multi_variations = {
        k: list(set(v)) for k, v in payee_variations.items()
        if len(set(v)) > 2
    }

    # Print report
    print(f"\n{'='*65}")
    print(f"  TRANSACTION REVIEW - Last {days} days")
    print(f"  Memo threshold: ${memo_threshold:.2f}")
    print(f"{'='*65}")

    issues_found = False

    if uncategorized:
        issues_found = True
        print(f"\n  UNCATEGORIZED TRANSACTIONS ({len(uncategorized)})")
        print(f"  {'-'*60}")
        for txn in sorted(uncategorized, key=lambda x: x["date"]):
            amt = format_currency(txn["amount"])
            print(f"    {txn['date']}  {txn['payee_name']:<25}  {amt:>10}  [{txn['account_name']}]")

    if missing_memo:
        issues_found = True
        print(f"\n  MISSING MEMO (transactions >= ${memo_threshold:.2f}) ({len(missing_memo)})")
        print(f"  {'-'*60}")
        for txn in sorted(missing_memo, key=lambda x: x["date"]):
            amt = format_currency(txn["amount"])
            print(f"    {txn['date']}  {txn['payee_name']:<25}  {amt:>10}  [{txn['category_name']}]")

    if unapproved:
        issues_found = True
        print(f"\n  UNAPPROVED TRANSACTIONS ({len(unapproved)})")
        print(f"  {'-'*60}")
        for txn in sorted(unapproved, key=lambda x: x["date"]):
            amt = format_currency(txn["amount"])
            print(f"    {txn['date']}  {txn['payee_name']:<25}  {amt:>10}  [{txn['account_name']}]")

    if multi_variations:
        issues_found = True
        print(f"\n  PAYEES WITH MULTIPLE IMPORT NAMES ({len(multi_variations)})")
        print(f"  (May indicate inconsistent categorization)")
        print(f"  {'-'*60}")
        for payee, variations in sorted(multi_variations.items()):
            print(f"    {payee}:")
            for v in variations[:5]:  # Show first 5
                print(f"      - {v}")

    if not issues_found:
        print(f"\n  No issues found. All transactions look clean.")

    print(f"\n{'='*65}")

    # Summary stats
    total_txns = len(txns)
    total_issues = len(uncategorized) + len(missing_memo) + len(unapproved)

    print(f"\n  Summary: {total_txns} transactions reviewed, {total_issues} issues flagged")
    print()


def main():
    parser = argparse.ArgumentParser(description="Review transactions for issues")
    parser.add_argument("--days", "-d", type=int, default=30,
                        help="Number of days to review (default: 30)")
    parser.add_argument("--memo-threshold", "-m", type=float, default=100,
                        help="Flag missing memos above this amount (default: $100)")
    args = parser.parse_args()

    review_transactions(days=args.days, memo_threshold=args.memo_threshold)


if __name__ == "__main__":
    main()
