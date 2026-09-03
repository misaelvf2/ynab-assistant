#!/usr/bin/env python3
"""
Assign Month — plan / apply / undo for the "budgeted" amount of every category.

  plan   Propose an assignment per category for one month. Read-only.
         Modes:
           cover   (default for past months)  assign just enough to bring each
                   overspent category back to zero — what YNAB's "cover
                   overspending" does, category by category.
           target  (default for the current month)  assign caps from
                   spending_caps, contributions from savings_targets, YNAB
                   NEED goals, or the rounded average of recent spending.
  apply  Write the proposed amounts. One API request per changed category.
  undo   Restore the previous amounts recorded in a journal.

Examples:
  uv run python scripts/assign_month.py plan --month 2026-04
  uv run python scripts/assign_month.py plan --month 2026-09 --mode target
  uv run python scripts/assign_month.py apply changes/plans/<file>.json --dry-run
  uv run python scripts/assign_month.py undo changes/journals/<file>.json
"""
import argparse
import math
from datetime import date

from dateutil.relativedelta import relativedelta

from ynab_assistant import (
    YNABClient, format_currency, load_config, save_report, dollars_to_milliunits,
)
from ynab_assistant.changes import (
    save_plan, load_plan, apply_month_category_changes, undo_journal, summarize_journal,
)


def round_up_dollars(mu: int, step: int = 5) -> int:
    """Round milliunits up to the next $step."""
    dollars = mu / 1000
    return int(math.ceil(dollars / step) * step) * 1000


def typical_spend(client, category_id: str, month: str, months: int) -> tuple[int, str]:
    """Typical monthly outflow over the previous ``months`` months.

    If the category had activity in at least half of those months it is
    treated as recurring and the median of the non-zero months is used
    (robust to one missing bill); otherwise the plain average.
    """
    start = date.fromisoformat(month)
    values = []
    for i in range(1, months + 1):
        m = (start - relativedelta(months=i)).isoformat()
        for c in client.get_month(m)["categories"]:
            if c["id"] == category_id:
                values.append(max(0, -c["activity"]))
                break
    if not values:
        return 0, "no history"
    nonzero = sorted(v for v in values if v)
    if len(nonzero) * 2 >= len(values):
        mid = len(nonzero) // 2
        median = nonzero[mid] if len(nonzero) % 2 else (nonzero[mid - 1] + nonzero[mid]) // 2
        return median, f"median of last {len(values)} months"
    return sum(values) // len(values), f"avg of last {len(values)} months"


def build_plan(month: str, mode: str, history: int) -> tuple[dict, str]:
    client = YNABClient()
    cfg = load_config()
    skip = set(cfg["interpretation"]["skip_category_groups"])
    caps = {v["category_id"]: v for v in cfg.get("spending_caps", {}).values()}
    savings = {v["category_id"]: v for v in cfg.get("savings_targets", {}).values()}

    month_data = client.get_month(month)
    current_month = date.today().strftime("%Y-%m-01")
    # Assigning in a past month reduces Ready to Assign in every later month too,
    # so the binding constraint is the smaller of the plan month and the current month.
    rta_plan_month = month_data["to_be_budgeted"]
    rta_current = client.get_month(current_month)["to_be_budgeted"] if month < current_month else rta_plan_month
    ready_to_assign = min(rta_plan_month, rta_current)
    entries = []

    for c in month_data["categories"]:
        if c["deleted"] or c["hidden"] or c["category_group_name"] in skip:
            continue
        if c["budgeted"] < 0:
            continue  # credit-card payment tracking
        budgeted, activity, balance = c["budgeted"], c["activity"], c["balance"]

        if mode == "cover":
            proposed = budgeted - balance if balance < 0 else budgeted
            basis = "cover overspending" if balance < 0 else "no change"
        else:
            if c["id"] in savings:
                # Contributions are additive: the fund's existing balance is the point.
                target, basis = dollars_to_milliunits(savings[c["id"]]["monthly_contribution"]), "savings target"
                needed = target
            else:
                if c["id"] in caps:
                    target, basis = dollars_to_milliunits(caps[c["id"]]["monthly_limit"]), "spending cap"
                elif c.get("goal_type") == "NEED" and c.get("goal_target"):
                    target, basis = c["goal_target"], "YNAB goal"
                else:
                    typical, basis = typical_spend(client, c["id"], month, history)
                    target = round_up_dollars(typical)
                # Money already available from prior months reduces what is needed now.
                carried = balance - budgeted - activity
                needed = max(target - max(carried, 0), 0)
            proposed = max(budgeted, needed)
            if proposed == budgeted:
                basis = "no change"

        if proposed == budgeted:
            continue
        entries.append({
            "month": month,
            "category_id": c["id"],
            "before": {"budgeted": budgeted},
            "after": {"budgeted": proposed},
            "context": {
                "category_name": c["name"],
                "group": c["category_group_name"],
                "activity": activity,
                "balance": balance,
                "basis": basis,
            },
        })

    total_delta = sum(e["after"]["budgeted"] - e["before"]["budgeted"] for e in entries)
    plan = {
        "type": "assign",
        "month": month,
        "mode": mode,
        "ready_to_assign_before": ready_to_assign,
        "ready_to_assign_plan_month": rta_plan_month,
        "ready_to_assign_current_month": rta_current,
        "total_delta": total_delta,
        "over_assigns": total_delta > ready_to_assign,
        "entries": entries,
    }
    return plan, render_plan_report(plan)


def render_plan_report(plan: dict) -> str:
    lines = [
        f"# Assignment Plan - {plan['month'][:7]} ({plan['mode']} mode)",
        "",
        f"**Ready to Assign ({plan['month'][:7]}):** {format_currency(plan['ready_to_assign_plan_month'])}"
        + (f" | **now:** {format_currency(plan['ready_to_assign_current_month'])}"
           if plan['ready_to_assign_current_month'] != plan['ready_to_assign_plan_month'] else ""),
        f"**Total to assign:** {format_currency(plan['total_delta'])}",
        f"**Ready to Assign after (worst case):** {format_currency(plan['ready_to_assign_before'] - plan['total_delta'])}",
        f"**Changes:** {len(plan['entries'])} categories",
        "",
    ]
    if plan["over_assigns"]:
        lines += ["**WARNING: this plan assigns more than is available. Apply requires --allow-overassign.**", ""]
    lines += ["| Category | Group | Budgeted | Spent | Balance | Proposed | Delta | Basis |",
              "|----------|-------|----------|-------|---------|----------|-------|-------|"]
    for e in sorted(plan["entries"], key=lambda x: (x["context"]["group"], x["context"]["category_name"])):
        c = e["context"]
        delta = e["after"]["budgeted"] - e["before"]["budgeted"]
        lines.append(
            f"| {c['category_name']} | {c['group']} | {format_currency(e['before']['budgeted'])} | "
            f"{format_currency(-c['activity'])} | {format_currency(c['balance'])} | "
            f"{format_currency(e['after']['budgeted'])} | {format_currency(delta)} | {c['basis']} |"
        )
    return "\n".join(lines)


def cmd_plan(args):
    month = f"{args.month}-01" if len(args.month) == 7 else args.month
    today_month = date.today().strftime("%Y-%m-01")
    mode = args.mode or ("cover" if month < today_month else "target")
    plan, report = build_plan(month, mode, args.history)
    path = save_plan(f"assign_{month[:7]}", plan)
    md, _ = save_report("assignment-plan", report, month_str=month[:7])
    print(report)
    print(f"\n---\nPlan saved to: {path}\nReport: {md}")
    print(f"\nNext: uv run python scripts/assign_month.py apply {path} --dry-run")


def cmd_apply(args):
    plan = load_plan(args.plan)
    if plan.get("type") != "assign":
        raise SystemExit("not an assignment plan")
    if plan.get("over_assigns") and not args.allow_overassign:
        raise SystemExit("plan assigns more than Ready to Assign; pass --allow-overassign to proceed")
    client = YNABClient(use_cache=False)
    current_month = date.today().strftime("%Y-%m-01")
    rta_before = client.get_month(current_month)["to_be_budgeted"]
    journal = apply_month_category_changes(
        client, plan["entries"], f"assign_{plan['month'][:7]}", plan_file=args.plan,
        dry_run=args.dry_run, force=args.force,
    )
    print(summarize_journal(journal, dry_run=args.dry_run))
    rta_after = client.get_month(current_month)["to_be_budgeted"]
    print(f"Ready to Assign ({current_month[:7]}): {format_currency(rta_before)} -> {format_currency(rta_after)}")


def cmd_undo(args):
    client = YNABClient(use_cache=False)
    journal = undo_journal(client, args.journal, dry_run=args.dry_run, force=args.force)
    print(summarize_journal(journal, dry_run=args.dry_run))


def main():
    parser = argparse.ArgumentParser(description="Assign budget amounts safely (plan/apply/undo)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--month", default=date.today().strftime("%Y-%m"), help="YYYY-MM")
    p.add_argument("--mode", choices=["cover", "target"])
    p.add_argument("--history", type=int, default=6, help="Months of history used in target mode")
    p.set_defaults(func=cmd_plan)

    a = sub.add_parser("apply")
    a.add_argument("plan")
    a.add_argument("--allow-overassign", action="store_true")
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
