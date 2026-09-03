#!/usr/bin/env python3
"""
Hygiene Status — how far the budget has drifted, month by month. Read-only.

Reports per month: income, assigned, spending, Ready to Assign, unapproved,
uncategorized, and overspent categories. Flags recurring payees that stopped
appearing, and lists change journals (what has been applied, and can be undone).

  uv run python scripts/hygiene_status.py [--months N]
"""
import argparse
from collections import defaultdict
from datetime import date

from ynab_assistant import YNABClient, format_currency, load_config, save_report
from ynab_assistant.changes import list_journals, load_journal
from ynab_assistant.hygiene import is_real, month_range, payee_key, on_budget_account_ids, needs_category


def hygiene_status(months: int = 6) -> str:
    client = YNABClient()
    cfg = load_config()
    skip = set(cfg["interpretation"]["skip_category_groups"])
    month_strs = month_range(months)

    on_budget = on_budget_account_ids(client)
    txns = [t for t in client.get_transactions(since_date=month_strs[0]) if not t["deleted"]]
    by_month = defaultdict(list)
    for t in txns:
        by_month[t["date"][:7]].append(t)

    rows = []
    for m in month_strs:
        md = client.get_month(m)
        cats = [c for c in md["categories"] if not c["deleted"] and c["category_group_name"] not in skip]
        spent = sum(-c["activity"] for c in cats if c["activity"] < 0)
        overspent = [c["name"] for c in cats if c["balance"] < 0]
        mt = by_month.get(m[:7], [])
        rows.append({
            "month": m[:7],
            "income": md["income"],
            "budgeted": md["budgeted"],
            "spent": spent,
            "rta": md["to_be_budgeted"],
            "unapproved": sum(1 for t in mt if not t["approved"]),
            "uncategorized": sum(1 for t in mt if needs_category(t, on_budget)),
            "overspent": overspent,
        })

    # Recurring payees that went missing in the last complete month
    complete = [r["month"] for r in rows[:-1]]
    missing = []
    if len(complete) >= 3:
        last, prior = complete[-1], complete[-4:-1]
        seen = defaultdict(set)
        for t in txns:
            if is_real(t) and t["amount"] < 0 and t["date"][:7] in complete:
                seen[payee_key(t)].add(t["date"][:7])
        for payee, ms in seen.items():
            if all(p in ms for p in prior) and last not in ms:
                missing.append(payee)

    # Unmatched transfer pairs: same date, opposite amounts, two different
    # on-budget accounts, neither side recorded as a transfer (e.g. a card
    # payment imported on both sides). YNAB should link these; fix in the UI.
    pairs = []
    by_key = defaultdict(list)
    for t in txns:
        if is_real(t) and t["account_id"] in on_budget:
            by_key[(t["date"], abs(t["amount"]))].append(t)
    for group in by_key.values():
        outs = [t for t in group if t["amount"] < 0]
        ins = [t for t in group if t["amount"] > 0]
        for o in outs:
            for i in ins:
                if o["account_id"] != i["account_id"]:
                    pairs.append((o, i))

    journals = []
    for path in list_journals():
        j = load_journal(path)
        entries = [e for e in j["entries"] if not e.get("dry_run")]
        journals.append((path.name, j["label"], len(entries),
                         sum(1 for e in entries if e.get("verified")), j.get("undo_of")))

    total_unapproved = sum(r["unapproved"] for r in rows)
    total_uncat = sum(r["uncategorized"] for r in rows)
    unassigned = [r["month"] for r in rows if r["budgeted"] == 0]

    lines = [
        f"# Budget Hygiene Status - {date.today()}",
        "",
        "## Executive Summary",
        "",
        f"Last {months} months: {total_unapproved} unapproved, {total_uncat} uncategorized, "
        f"{len(unassigned)} month(s) with nothing assigned"
        + (f" ({', '.join(unassigned)})" if unassigned else "") + ".",
        f"Ready to Assign now: {format_currency(rows[-1]['rta'])}.",
        "",
        "## By Month",
        "",
        "| Month | Income | Assigned | Spent | Ready to Assign | Unapproved | Uncategorized | Overspent cats |",
        "|-------|--------|----------|-------|-----------------|------------|---------------|----------------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['month']} | {format_currency(r['income'])} | {format_currency(r['budgeted'])} | "
            f"{format_currency(r['spent'])} | {format_currency(r['rta'])} | {r['unapproved']} | "
            f"{r['uncategorized']} | {len(r['overspent'])} |"
        )
    if missing:
        lines += ["", f"## Recurring payees missing in {complete[-1]}", "",
                  "*Seen in each of the three prior months but not in the last complete month.*", ""]
        lines += [f"- {p}" for p in sorted(missing)]
    if pairs:
        lines += ["", f"## Possible unmatched transfers ({len(pairs)})", "",
                  "*Same date and amount, opposite sign, two accounts, not linked as a transfer.*", "",
                  "| Date | Amount | From | To | Payees |", "|------|--------|------|----|--------|"]
        for o, i in sorted(pairs, key=lambda p: p[0]["date"])[:40]:
            lines.append(f"| {o['date']} | {format_currency(-o['amount'])} | {o['account_name']} | {i['account_name']} | {o['payee_name']} / {i['payee_name']} |")
    lines += ["", "## Change journals", ""]
    if journals:
        lines += ["| Journal | Label | Applied | Verified | Undo of |", "|---------|-------|---------|----------|---------|"]
        lines += [f"| {n} | {l} | {a} | {v} | {u or '-'} |" for n, l, a, v, u in journals]
    else:
        lines.append("None yet.")
    lines += ["", "## Suggested order", "",
              "1. `scripts/categorize_transactions.py plan` then apply confident suggestions",
              "2. `scripts/approve_transactions.py plan` then apply SAFE entries",
              "3. `scripts/assign_month.py plan --month YYYY-MM` for each unassigned month (oldest first)",
              "4. Re-run this script; repeat for whatever remains"]
    report = "\n".join(lines)
    md, html = save_report("hygiene-status", report)
    print(report)
    print(f"\n---\nReports saved to:\n  {md}\n  {html}")
    return report


def main():
    parser = argparse.ArgumentParser(description="Budget hygiene status (read-only)")
    parser.add_argument("--months", type=int, default=6)
    args = parser.parse_args()
    hygiene_status(args.months)


if __name__ == "__main__":
    main()
