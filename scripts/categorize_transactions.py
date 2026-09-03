#!/usr/bin/env python3
"""
Categorize Transactions — plan / apply / undo.

  plan   For every uncategorized transaction, suggest a category from the
         payee's approved history with a confidence score. Read-only.
         The plan JSON is meant to be edited: set "category_id"/"category_name"
         and flip "decision" to "suggest" for the MANUAL ones you resolve.
  apply  Set category_id for SUGGEST entries at or above --min-confidence.
         Does not approve (run approve_transactions.py afterwards).
  undo   Clear the categories a journal set (back to uncategorized).

Examples:
  uv run python scripts/categorize_transactions.py plan --since 2026-04-01
  uv run python scripts/categorize_transactions.py apply changes/plans/<file>.json --dry-run
  uv run python scripts/categorize_transactions.py undo changes/journals/<file>.json
"""
import argparse
from datetime import date, timedelta

from ynab_assistant import YNABClient, format_currency, save_report, load_config
from ynab_assistant.changes import (
    save_plan, load_plan, apply_transaction_changes, undo_journal, summarize_journal,
)
from ynab_assistant.hygiene import PayeeHistory, load_history, is_split, txn_context, on_budget_account_ids, needs_category


def load_payee_rules(client) -> list[tuple[str, str, str]]:
    """config.json → hygiene.payee_rules: {"payee substring": "Category Name"}.

    Returns (substring, category_id, category_name) triples. Unknown category
    names are reported and skipped.
    """
    rules = load_config().get("hygiene", {}).get("payee_rules", {})
    by_name = {}
    for group in client.get_categories():
        for c in group["categories"]:
            if not c["deleted"]:
                by_name[c["name"].lower()] = (c["id"], c["name"])
    out = []
    for needle, cat_name in rules.items():
        match = by_name.get(cat_name.lower())
        if not match:
            print(f"warning: payee rule '{needle}' names unknown category '{cat_name}'")
            continue
        out.append((needle.lower(), match[0], match[1]))
    return out


def match_rule(txn: dict, rules) -> tuple[str, str] | None:
    hay = " | ".join(filter(None, [txn.get("payee_name"), txn.get("import_payee_name")])).lower()
    for needle, cat_id, cat_name in rules:
        if needle in hay:
            return cat_id, cat_name
    return None


def build_plan(since: str, month: str | None, min_confidence: float, min_history: int):
    client = YNABClient()
    history = PayeeHistory(load_history(client))
    rules = load_payee_rules(client)

    on_budget = on_budget_account_ids(client)
    txns = client.get_transactions(since_date=since)
    candidates = [t for t in txns if needs_category(t, on_budget) and not is_split(t)]
    if month:
        candidates = [t for t in candidates if t["date"].startswith(month)]

    entries = []
    for t in sorted(candidates, key=lambda x: x["date"]):
        rule = match_rule(t, rules)
        if rule:
            entries.append({
                "id": t["id"], "decision": "suggest", "category_id": rule[0],
                "category_name": rule[1], "confidence": 1.0, "samples": 0, "basis": "payee rule",
                "alternatives": [], "before": {"category_id": None}, "context": txn_context(t),
            })
            continue
        s = history.suggest(t)
        confident = s["samples"] >= min_history and s["confidence"] >= min_confidence
        entries.append({
            "id": t["id"],
            "decision": "suggest" if confident else "manual",
            "category_id": s["category_id"] if confident else None,
            "category_name": s["category_name"] if confident else None,
            "confidence": s["confidence"],
            "samples": s["samples"],
            "alternatives": ([{"category_name": s["category_name"], "category_id": s["category_id"],
                               "count": round(s["confidence"] * s["samples"])}] if s["category_id"] and not confident else [])
                            + s["alternatives"],
            "before": {"category_id": None},
            "context": txn_context(t),
        })

    plan = {
        "type": "categorize",
        "since": since,
        "month": month,
        "min_confidence": min_confidence,
        "min_history": min_history,
        "entries": entries,
    }
    return plan, render_plan_report(plan)


def render_plan_report(plan: dict) -> str:
    entries = plan["entries"]
    suggest = [e for e in entries if e["decision"] == "suggest"]
    manual = [e for e in entries if e["decision"] == "manual"]
    lines = [
        f"# Categorization Plan - {date.today()}",
        "",
        f"**Since:** {plan['since']}" + (f" (month {plan['month']})" if plan.get("month") else ""),
        f"**Uncategorized:** {len(entries)} | **Confident suggestions:** {len(suggest)} | **Manual:** {len(manual)}",
        f"**Thresholds:** confidence >= {plan['min_confidence']}, history >= {plan['min_history']}",
        "",
        "## Confident suggestions (by payee)",
        "",
        "| Payee | Suggested category | Basis | Count | Total |",
        "|-------|--------------------|-------|-------|-------|",
    ]
    groups = {}
    for e in suggest:
        c = e["context"]
        basis = e.get("basis") or f"{e['confidence']:.0%} of {e['samples']} prior"
        groups.setdefault((c["payee"], e["category_name"], basis), []).append(c["amount"])
    for (payee, cat, basis), amounts in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"| {payee} | {cat} | {basis} | {len(amounts)} | {format_currency(sum(amounts))} |")
    lines += ["", f"## Manual ({len(manual)})", "",
              "| Date | Payee | Amount | Account | Best guess | Alternatives |",
              "|------|-------|--------|---------|------------|--------------|"]
    for e in manual:
        c = e["context"]
        alts = e["alternatives"]
        best = f"{alts[0]['category_name']} ({alts[0]['count']}/{e['samples']})" if alts else "no history"
        others = ", ".join(f"{a['category_name']} ({a['count']})" for a in alts[1:]) or "-"
        lines.append(f"| {c['date']} | {c['payee']} | {format_currency(c['amount'])} | {c['account']} | {best} | {others} |")
    lines += ["", "To resolve MANUAL entries either add a rule to config.json → hygiene.payee_rules",
              "(\"payee substring\": \"Category Name\") and re-plan, or edit the plan JSON: set",
              "`category_id` and `category_name`, change `decision` to `suggest`, then apply."]
    return "\n".join(lines)


def cmd_plan(args):
    since = args.since or (date.today() - timedelta(days=args.days)).isoformat()
    plan, report = build_plan(since, args.month, args.min_confidence, args.min_history)
    path = save_plan("categorize", plan)
    md, _ = save_report("categorization-plan", report)
    print(report)
    print(f"\n---\nPlan saved to: {path}\nReport: {md}")
    print(f"\nNext: uv run python scripts/categorize_transactions.py apply {path} --dry-run")


def cmd_apply(args):
    plan = load_plan(args.plan)
    if plan.get("type") != "categorize":
        raise SystemExit("not a categorization plan")
    changes = []
    for e in plan["entries"]:
        if e["decision"] != "suggest" or not e.get("category_id"):
            continue
        if e.get("confidence", 1.0) < args.min_confidence:
            continue
        after = {"category_id": e["category_id"]}
        if args.and_approve:
            after["approved"] = True
        changes.append({"id": e["id"], "before": e["before"], "after": after,
                        "context": {**e["context"], "new_category": e["category_name"]}})
    if args.limit:
        changes = changes[:args.limit]
    client = YNABClient(use_cache=False)
    journal = apply_transaction_changes(
        client, changes, "categorize", plan_file=args.plan, dry_run=args.dry_run,
        force=args.force, since_date=plan.get("since"),
    )
    print(summarize_journal(journal, dry_run=args.dry_run))


def cmd_undo(args):
    client = YNABClient(use_cache=False)
    journal = undo_journal(client, args.journal, dry_run=args.dry_run, force=args.force)
    print(summarize_journal(journal, dry_run=args.dry_run))


def main():
    parser = argparse.ArgumentParser(description="Categorize transactions safely (plan/apply/undo)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--since")
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--month")
    p.add_argument("--min-confidence", type=float, default=0.8)
    p.add_argument("--min-history", type=int, default=2)
    p.set_defaults(func=cmd_plan)

    a = sub.add_parser("apply")
    a.add_argument("plan")
    a.add_argument("--min-confidence", type=float, default=0.0,
                   help="Extra floor at apply time (plan already filtered)")
    a.add_argument("--and-approve", action="store_true", help="Also mark approved")
    a.add_argument("--limit", type=int)
    a.add_argument("--dry-run", action="store_true")
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_apply)

    u = sub.add_parser("undo")
    u.add_argument("journal")
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--force", action="store_true")
    u.set_defaults(func=cmd_undo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
