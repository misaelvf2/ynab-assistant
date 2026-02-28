#!/usr/bin/env python3
"""
Transaction Approval - Review unapproved transactions against historical patterns
"""
import argparse
import requests
from collections import defaultdict
from datetime import date, timedelta
from ynab_client import (
    YNABClient, load_token, load_config, format_currency,
    milliunits_to_dollars, save_report
)


def get_payee_history(transactions: list, payee_name: str, limit: int = 10) -> list:
    """Get historical transactions for a payee."""
    matches = [
        t for t in transactions
        if t['payee_name'] and t['payee_name'].lower() == payee_name.lower()
        and t['approved']
    ]
    return sorted(matches, key=lambda x: x['date'])[-limit:]


def analyze_consistency(txn: dict, history: list) -> dict:
    """Analyze if a transaction is consistent with historical patterns."""
    result = {
        'history_count': len(history),
        'consistent': True,
        'notes': []
    }

    if not history:
        result['consistent'] = False
        result['notes'].append('No prior transactions from this payee')
        return result

    # Check category consistency
    categories = set(t['category_name'] for t in history)
    if txn['category_name'] not in categories:
        result['notes'].append(f"Category '{txn['category_name']}' differs from historical: {', '.join(categories)}")

    # Check amount range
    amounts = [abs(t['amount']) for t in history]
    min_amt, max_amt = min(amounts), max(amounts)
    txn_amt = abs(txn['amount'])

    if txn_amt < min_amt * 0.5 or txn_amt > max_amt * 2:
        result['notes'].append(
            f"Amount ${milliunits_to_dollars(txn_amt):.2f} outside typical range "
            f"(${milliunits_to_dollars(min_amt):.2f} - ${milliunits_to_dollars(max_amt):.2f})"
        )

    # Check account consistency
    accounts = set(t['account_name'] for t in history)
    if txn['account_name'] not in accounts:
        result['notes'].append(f"Account '{txn['account_name']}' differs from historical: {', '.join(accounts)}")

    if result['notes']:
        result['consistent'] = False

    return result


def approve_transaction(budget_id: str, txn_id: str, token: str) -> bool:
    """Approve a transaction via YNAB API."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    resp = requests.patch(
        f'https://api.ynab.com/v1/budgets/{budget_id}/transactions/{txn_id}',
        headers=headers,
        json={'transaction': {'approved': True}}
    )
    return resp.status_code == 200


def review_and_approve(days: int = 30, auto_approve: bool = False, dry_run: bool = False) -> str:
    """Review unapproved transactions and optionally approve consistent ones."""
    client = YNABClient()
    config = load_config()
    token = load_token()
    budget_id = config['ynab']['budget_id']
    today = date.today()

    # Get recent transactions
    since = today - timedelta(days=days)
    recent_txns = client.get_transactions(since_date=since.strftime('%Y-%m-%d'))

    # Get historical transactions for comparison (1 year)
    history_since = today - timedelta(days=365)
    all_txns = client.get_transactions(since_date=history_since.strftime('%Y-%m-%d'))

    UNCATEGORIZED_NAMES = {'Uncategorized', 'Inflow: Ready to Assign', '', None}

    # Filter to non-deleted, non-transfer transactions needing attention
    unapproved = [
        t for t in recent_txns
        if not t['deleted']
        and t['transfer_account_id'] is None
        and (not t['approved'] or t.get('category_name') in UNCATEGORIZED_NAMES)
    ]

    if not unapproved:
        msg = f"No transactions needing attention in the last {days} days."
        print(msg)
        return msg

    needs_approval = [t for t in unapproved if not t['approved']]
    needs_categorization = [t for t in unapproved if t['approved'] and t.get('category_name') in UNCATEGORIZED_NAMES]

    lines = [
        f"# Transaction Approval Review - {today}",
        f"",
        f"**Period:** Last {days} days",
        f"**Transactions needing attention:** {len(unapproved)}",
    ]
    if needs_approval:
        lines.append(f"**Unapproved:** {len(needs_approval)}")
    if needs_categorization:
        lines.append(f"**Uncategorized:** {len(needs_categorization)}")
    lines.extend([
        f"**Mode:** {'Dry run' if dry_run else 'Auto-approve consistent' if auto_approve else 'Review only'}",
        f"",
    ])

    approved_count = 0
    flagged_count = 0

    consistent_txns = []
    inconsistent_txns = []

    for txn in sorted(unapproved, key=lambda x: x['date']):
        payee = txn['payee_name'] or 'Unknown'
        history = get_payee_history(all_txns, payee)
        analysis = analyze_consistency(txn, history)

        txn_info = {
            'txn': txn,
            'history': history,
            'analysis': analysis
        }

        if analysis['consistent']:
            consistent_txns.append(txn_info)
        else:
            inconsistent_txns.append(txn_info)

    # Consistent transactions
    if consistent_txns:
        lines.extend([
            f"## Consistent with History ({len(consistent_txns)})",
            f"",
            f"| Date | Payee | Amount | Category | History | Action |",
            f"|------|-------|--------|----------|---------|--------|",
        ])

        for item in consistent_txns:
            txn = item['txn']
            history = item['history']

            # Build history summary
            if history:
                amounts = [abs(t['amount']) for t in history]
                avg_amt = sum(amounts) / len(amounts)
                hist_summary = f"{len(history)} prior (avg ${milliunits_to_dollars(avg_amt):.0f})"
            else:
                hist_summary = "None"

            action = ""
            if auto_approve and not dry_run:
                if approve_transaction(budget_id, txn['id'], token):
                    action = "Approved"
                    approved_count += 1
                else:
                    action = "Failed"
            elif auto_approve and dry_run:
                action = "Would approve"
                approved_count += 1
            else:
                action = "Consistent"

            lines.append(
                f"| {txn['date']} | {txn['payee_name']} | {format_currency(txn['amount'])} | "
                f"{txn['category_name']} | {hist_summary} | {action} |"
            )
        lines.append("")

    # Inconsistent transactions
    if inconsistent_txns:
        lines.extend([
            f"## Needs Review ({len(inconsistent_txns)})",
            f"",
        ])

        for item in inconsistent_txns:
            txn = item['txn']
            history = item['history']
            analysis = item['analysis']
            flagged_count += 1

            lines.extend([
                f"### {txn['payee_name']} - {format_currency(txn['amount'])}",
                f"",
                f"- **Date:** {txn['date']}",
                f"- **Category:** {txn['category_name']}",
                f"- **Account:** {txn['account_name']}",
                f"",
                f"**Issues:**",
            ])

            for note in analysis['notes']:
                lines.append(f"- {note}")

            if history:
                lines.extend([
                    f"",
                    f"**Recent history:**",
                ])
                for h in history[-5:]:
                    lines.append(
                        f"- {h['date']}: {format_currency(h['amount'])} ({h['category_name']})"
                    )

            lines.append("")

    # Summary
    lines.extend([
        f"---",
        f"",
        f"**Summary:** {len(consistent_txns)} consistent, {len(inconsistent_txns)} need review",
    ])

    if approved_count > 0:
        lines.append(f"**Approved:** {approved_count} transactions")

    report_content = "\n".join(lines)

    md_path, html_path = save_report("transaction-approval", report_content)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def main():
    parser = argparse.ArgumentParser(
        description="Review unapproved transactions against historical patterns"
    )
    parser.add_argument(
        "--days", "-d", type=int, default=30,
        help="Number of days to look back for unapproved transactions (default: 30)"
    )
    parser.add_argument(
        "--approve", "-a", action="store_true",
        help="Auto-approve transactions that are consistent with history"
    )
    parser.add_argument(
        "--dry-run", "-n", action="store_true",
        help="Show what would be approved without actually approving"
    )
    args = parser.parse_args()

    review_and_approve(
        days=args.days,
        auto_approve=args.approve,
        dry_run=args.dry_run
    )


if __name__ == "__main__":
    main()
