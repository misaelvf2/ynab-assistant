#!/usr/bin/env python3
"""
Approve Transactions — plan / apply / undo.

  plan   Classify unapproved transactions as SAFE (matches an established
         payee+category pattern) or REVIEW (anything unusual). Read-only.
  apply  Approve the SAFE entries of a plan. Live state is re-checked before
         every write; every write is verified and journaled.
  undo   Un-approve everything a journal approved.

Examples:
  uv run python scripts/approve_transactions.py plan --since 2026-04-01
  uv run python scripts/approve_transactions.py apply changes/plans/<file>.json --dry-run
  uv run python scripts/approve_transactions.py apply changes/plans/<file>.json --limit 50
  uv run python scripts/approve_transactions.py undo changes/journals/<file>.json
"""
import argparse
from collections import Counter
from datetime import date, timedelta

from ynab_assistant import YNABClient, format_currency, save_report
from ynab_assistant.changes import (
    save_plan, load_plan, apply_transaction_changes, undo_journal, summarize_journal,
)
from ynab_assistant.hygiene import (
    PayeeHistory, load_history, find_duplicate_ids, is_split, large_threshold_mu,
    txn_context, on_budget_account_ids, inflow_category_name,
)


YNAB_ADJUSTMENT_PAYEES = {"reconciliation balance adjustment", "starting balance"}


def classify(txn: dict, history: PayeeHistory, duplicates: set, min_history: int,
             large_mu: int, on_budget: set, inflow_name: str) -> list[str]:
    """Return reasons the transaction needs review; empty list means SAFE."""
    reasons = []
    if txn["id"] in duplicates:
        reasons.append("possible duplicate (same account/date/amount)")
    if txn["transfer_account_id"] is not None:
        # Transfers carry no category; approving them is harmless unless duplicated.
        return reasons
    payee = (txn.get("payee_name") or "").lower()
    if txn["account_id"] not in on_budget:
        # Tracking accounts: no category needed. YNAB's own adjustments are safe;
        # anything else is a manual entry worth a glance.
        if payee not in YNAB_ADJUSTMENT_PAYEES and history.distribution(txn).total() < min_history:
            reasons.append("tracking-account entry from unfamiliar payee")
        return reasons
    if is_split(txn):
        reasons.append("split transaction")
    if txn["category_id"] is None:
        reasons.append("uncategorized")
    if abs(txn["amount"]) >= large_mu:
        reasons.append(f"large amount (>= {format_currency(large_mu)})")
    if txn["category_id"] is not None and not is_split(txn):
        if txn["amount"] < 0 and txn["category_name"] == inflow_name:
            reasons.append("outflow categorized as inflow")
        support = history.supports(txn)
        if support < min_history:
            reasons.append(f"payee/category pattern seen only {support}x (need {min_history})")
    if txn["amount"] > 0 and history.supports(txn) < min_history:
        reasons.append("inflow from unfamiliar payee")
    return reasons


def build_plan(since: str, month: str | None, min_history: int) -> tuple[dict, str]:
    client = YNABClient()
    history = PayeeHistory(load_history(client))
    large_mu = large_threshold_mu()
    on_budget = on_budget_account_ids(client)
    inflow_name = inflow_category_name()

    all_txns = client.get_transactions(since_date=since)
    duplicates = find_duplicate_ids(all_txns)
    candidates = [t for t in all_txns if not t["deleted"] and not t["approved"]]
    if month:
        candidates = [t for t in candidates if t["date"].startswith(month)]

    entries = []
    for t in sorted(candidates, key=lambda x: x["date"]):
        reasons = classify(t, history, duplicates, min_history, large_mu, on_budget, inflow_name)
        entries.append({
            "id": t["id"],
            "decision": "safe" if not reasons else "review",
            "reasons": reasons,
            "before": {"approved": False},
            "after": {"approved": True},
            "context": txn_context(t),
            "is_transfer": t["transfer_account_id"] is not None,
        })

    plan = {
        "type": "approve",
        "since": since,
        "month": month,
        "min_history": min_history,
        "entries": entries,
    }
    return plan, render_plan_report(plan)


def render_plan_report(plan: dict) -> str:
    entries = plan["entries"]
    safe = [e for e in entries if e["decision"] == "safe"]
    review = [e for e in entries if e["decision"] == "review"]
    lines = [
        f"# Approval Plan - {date.today()}",
        "",
        f"**Since:** {plan['since']}" + (f" (month {plan['month']})" if plan.get("month") else ""),
        f"**Unapproved:** {len(entries)} | **Safe to approve:** {len(safe)} | **Needs review:** {len(review)}",
        "",
        "## Safe (by payee)",
        "",
        "| Payee | Category | Count | Total |",
        "|-------|----------|-------|-------|",
    ]
    groups = {}
    for e in safe:
        c = e["context"]
        key = (c["payee"], c["category_name"] if not e["is_transfer"] else "(transfer)")
        groups.setdefault(key, []).append(c["amount"])
    for (payee, cat), amounts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {payee} | {cat} | {len(amounts)} | {format_currency(sum(amounts))} |")
    lines += ["", f"## Needs review ({len(review)})", "",
              "| Date | Payee | Amount | Category | Reasons |",
              "|------|-------|--------|----------|---------|"]
    for e in review:
        c = e["context"]
        lines.append(
            f"| {c['date']} | {c['payee']} | {format_currency(c['amount'])} | "
            f"{c['category_name'] or '-'} | {'; '.join(e['reasons'])} |"
        )
    reason_counts = Counter(r.split(" (")[0] for e in review for r in e["reasons"])
    lines += ["", "## Review reasons", ""]
    for reason, n in reason_counts.most_common():
        lines.append(f"- {reason}: {n}")
    return "\n".join(lines)


def cmd_plan(args):
    since = args.since or (date.today() - timedelta(days=args.days)).isoformat()
    plan, report = build_plan(since, args.month, args.min_history)
    path = save_plan("approve", plan)
    md, html = save_report("approval-plan", report)
    print(report)
    print(f"\n---\nPlan saved to: {path}\nReport: {md}")
    print(f"\nNext: uv run python scripts/approve_transactions.py apply {path} --dry-run")


def cmd_apply(args):
    plan = load_plan(args.plan)
    if plan.get("type") != "approve":
        raise SystemExit("not an approval plan")
    wanted = {"safe"} | ({"review"} if args.include_review else set())
    changes = [e for e in plan["entries"] if e["decision"] in wanted]
    if args.limit:
        changes = changes[:args.limit]
    client = YNABClient(use_cache=False)
    journal = apply_transaction_changes(
        client, changes, "approve", plan_file=args.plan, dry_run=args.dry_run,
        force=args.force, since_date=plan.get("since"),
    )
    print(summarize_journal(journal, dry_run=args.dry_run))


def cmd_undo(args):
    client = YNABClient(use_cache=False)
    journal = undo_journal(client, args.journal, dry_run=args.dry_run, force=args.force)
    print(summarize_journal(journal, dry_run=args.dry_run))


def main():
    parser = argparse.ArgumentParser(description="Approve transactions safely (plan/apply/undo)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan", help="Classify unapproved transactions (read-only)")
    p.add_argument("--since", help="ISO date; default is --days ago")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--month", help="Restrict to YYYY-MM")
    p.add_argument("--min-history", type=int, default=2,
                   help="Prior approved payee+category matches required for SAFE (default 2)")
    p.set_defaults(func=cmd_plan)

    a = sub.add_parser("apply", help="Approve SAFE entries of a plan")
    a.add_argument("plan")
    a.add_argument("--include-review", action="store_true", help="Also approve REVIEW entries")
    a.add_argument("--limit", type=int, help="Apply at most N entries")
    a.add_argument("--dry-run", action="store_true", help="Check live state, write nothing")
    a.add_argument("--force", action="store_true", help="Apply even if live state drifted")
    a.set_defaults(func=cmd_apply)

    u = sub.add_parser("undo", help="Reverse a journal")
    u.add_argument("journal")
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--force", action="store_true")
    u.set_defaults(func=cmd_undo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
