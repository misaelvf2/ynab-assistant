#!/usr/bin/env python3
"""
Transaction Review Flags - Surface transactions that need attention
"""
import argparse
from collections import defaultdict
from datetime import date, timedelta
from ynab_assistant import (
    YNABClient, format_currency, milliunits_to_dollars,
    get_month_start_date, save_report, load_config
)


def generate_executive_summary(total_txns: int, uncategorized: list,
                                missing_memo: list, unapproved: list,
                                multi_variations: dict, days: int) -> str:
    """Generate plain-English executive summary."""
    lines = []

    total_issues = len(uncategorized) + len(missing_memo) + len(unapproved)

    lines.append(f"Reviewed {total_txns} transactions from the last {days} days.")

    if total_issues == 0:
        lines.append("No issues found.")
    else:
        lines.append(f"Found {total_issues} issues.")

        if uncategorized:
            total_uncat = sum(abs(t["amount"]) for t in uncategorized)
            lines.append(
                f"{len(uncategorized)} uncategorized ({format_currency(int(total_uncat))})."
            )

        if missing_memo:
            lines.append(f"{len(missing_memo)} large transactions missing memos.")

        if unapproved:
            lines.append(f"{len(unapproved)} unapproved.")

    if multi_variations:
        lines.append(
            f"{len(multi_variations)} payees with inconsistent naming from imports."
        )

    return " ".join(lines)


def review_transactions(days: int = 30, memo_threshold: float = 100) -> str:
    client = YNABClient()
    config = load_config()
    today = date.today()

    system_cats = config.get("interpretation", {}).get("system_categories", {})
    uncategorized_name = system_cats.get("uncategorized", "Uncategorized")

    since = today - timedelta(days=days)
    since_str = since.strftime("%Y-%m-%d")

    transactions = client.get_transactions(since_date=since_str)

    txns = [
        t for t in transactions
        if not t["deleted"] and t["transfer_account_id"] is None
    ]

    uncategorized = []
    missing_memo = []
    unapproved = []
    payee_variations = defaultdict(list)

    memo_threshold_mu = int(memo_threshold * 1000)

    for txn in txns:
        amount = txn["amount"]
        abs_amount = abs(amount)

        if txn["category_name"] == uncategorized_name or txn["category_id"] is None:
            if amount < 0:
                uncategorized.append(txn)

        if abs_amount >= memo_threshold_mu and not txn["memo"]:
            missing_memo.append(txn)

        if not txn["approved"]:
            unapproved.append(txn)

        if txn["import_payee_name"] and txn["payee_name"]:
            import_name = txn["import_payee_name"].lower().strip()
            clean_name = txn["payee_name"]
            payee_variations[clean_name].append(import_name)

    multi_variations = {
        k: list(set(v)) for k, v in payee_variations.items()
        if len(set(v)) > 2
    }

    exec_summary = generate_executive_summary(
        len(txns), uncategorized, missing_memo, unapproved, multi_variations, days
    )

    lines = [
        f"# Transaction Review - {today}",
        f"",
        f"**Period:** Last {days} days (since {since_str})",
        f"**Memo threshold:** ${memo_threshold:.2f}",
        f"**Transactions reviewed:** {len(txns)}",
        f"",
        f"## Executive Summary",
        f"",
        f"{exec_summary}",
        f"",
    ]

    issues_found = False

    if uncategorized:
        issues_found = True
        lines.extend([
            f"## Uncategorized Transactions ({len(uncategorized)})",
            f"",
            f"| Date | Payee | Amount | Account |",
            f"|------|-------|--------|---------|",
        ])
        for txn in sorted(uncategorized, key=lambda x: x["date"]):
            lines.append(
                f"| {txn['date']} | {txn['payee_name']} | {format_currency(txn['amount'])} | {txn['account_name']} |"
            )
        lines.append("")

    if missing_memo:
        issues_found = True
        lines.extend([
            f"## Missing Memo (>= ${memo_threshold:.2f}) ({len(missing_memo)})",
            f"",
            f"| Date | Payee | Amount | Category |",
            f"|------|-------|--------|----------|",
        ])
        for txn in sorted(missing_memo, key=lambda x: x["date"]):
            lines.append(
                f"| {txn['date']} | {txn['payee_name']} | {format_currency(txn['amount'])} | {txn['category_name']} |"
            )
        lines.append("")

    if unapproved:
        issues_found = True
        lines.extend([
            f"## Unapproved Transactions ({len(unapproved)})",
            f"",
            f"| Date | Payee | Amount | Account |",
            f"|------|-------|--------|---------|",
        ])
        for txn in sorted(unapproved, key=lambda x: x["date"]):
            lines.append(
                f"| {txn['date']} | {txn['payee_name']} | {format_currency(txn['amount'])} | {txn['account_name']} |"
            )
        lines.append("")

    if multi_variations:
        issues_found = True
        lines.extend([
            f"## Payees with Multiple Import Names ({len(multi_variations)})",
            f"",
            f"*May indicate inconsistent categorization*",
            f"",
        ])
        for payee, variations in sorted(multi_variations.items()):
            lines.append(f"**{payee}:**")
            for v in variations[:5]:
                lines.append(f"- {v}")
            lines.append("")

    if not issues_found:
        lines.extend([
            f"## All Clear",
            f"",
            f"No issues found.",
            f"",
        ])

    total_issues = len(uncategorized) + len(missing_memo) + len(unapproved)
    lines.extend([
        f"---",
        f"",
        f"**Summary:** {len(txns)} transactions reviewed, {total_issues} issues flagged",
    ])

    report_content = "\n".join(lines)

    md_path, html_path = save_report("transaction-review", report_content)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


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
