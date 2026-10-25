#!/usr/bin/env python3
"""
Category Habits - Purchase-level analysis of one spending category

Breaks a category's transactions down by purchase size, merchant, weekday and
month, and splits each month's change into frequency (purchases per week)
versus ticket size (average purchase).
"""
import argparse
import json
import statistics
from collections import defaultdict
from datetime import date

from ynab_assistant import YNABClient, save_report

BUCKETS = [(0, 15, "Under $15"), (15, 30, "$15–30"), (30, 60, "$30–60"), (60, 100, "$60–100"), (100, None, "$100+")]
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def find_category(client: YNABClient, name: str) -> dict:
    for group in client.get_categories():
        for cat in group["categories"]:
            if cat["name"].lower() == name.lower() and not cat.get("deleted"):
                return cat
    raise SystemExit(f"No category named '{name}'")


def category_transactions(client: YNABClient, category_id: str, since: str) -> list:
    """One row per purchase in the category, counting split lines separately."""
    rows = []
    for t in client.get_transactions(since_date=since):
        if t.get("deleted") or t["date"] < since:
            continue
        parts = [s for s in (t.get("subtransactions") or []) if not s.get("deleted")] or [t]
        for p in parts:
            if p.get("category_id") != category_id:
                continue
            rows.append({
                "id": p["id"],
                "date": t["date"],
                "payee": p.get("payee_name") or t.get("payee_name") or "",
                "amount": -p["amount"] / 1000,
            })
    return sorted(rows, key=lambda r: (r["date"], r["id"]))


def bucket_of(amount: float) -> str:
    for lo, hi, label in BUCKETS:
        if amount >= lo and (hi is None or amount < hi):
            return label
    return BUCKETS[0][2]


def analyze(name: str, since: str, cap: float = None, json_out: str = None) -> str:
    client = YNABClient()
    cat = find_category(client, name)
    rows = category_transactions(client, cat["id"], since)
    if json_out:
        with open(json_out, "w") as f:
            json.dump(rows, f, indent=1)
    if not rows:
        return f"No {name} transactions since {since}."

    today = date.today()
    start = date.fromisoformat(since)
    days = (today - start).days + 1
    amounts = [r["amount"] for r in rows if r["amount"] > 0]
    total = sum(r["amount"] for r in rows)
    active_days = {r["date"] for r in rows}

    lines = [
        f"# {name} Habits — {since} to {today.isoformat()}",
        "",
        "## Summary",
        "",
        f"- **Total:** ${total:,.2f} across {len(rows)} purchases",
        f"- **Per day:** ${total / days:,.2f} | **Purchases per week:** {len(rows) / days * 7:.1f}",
        f"- **Median purchase:** ${statistics.median(amounts):,.2f} | **Average:** ${statistics.mean(amounts):,.2f}",
        f"- **Days with a purchase:** {len(active_days)} of {days} ({len(active_days) / days:.0%})",
        "",
        "## By Purchase Size",
        "",
        "| Size | Purchases | % of purchases | Dollars | % of dollars |",
        "|------|----------:|---------------:|--------:|-------------:|",
    ]
    by_bucket = defaultdict(list)
    for a in amounts:
        by_bucket[bucket_of(a)].append(a)
    for _, _, label in BUCKETS:
        xs = by_bucket[label]
        lines.append(f"| {label} | {len(xs)} | {len(xs) / len(amounts):.0%} | ${sum(xs):,.2f} | {sum(xs) / sum(amounts):.0%} |")

    by_month = defaultdict(list)
    for r in rows:
        by_month[r["date"][:7]].append(r["amount"])
    lines += ["", "## By Month", "", "| Month | Total | Purchases | Per week | Average |" + (" vs cap |" if cap else ""),
              "|-------|------:|----------:|---------:|--------:|" + ("-------:|" if cap else "")]
    for month, xs in sorted(by_month.items()):
        y, m = map(int, month.split("-"))
        first = max(start, date(y, m, 1))
        last = today if (y, m) == (today.year, today.month) else date(y + m // 12, m % 12 + 1, 1).replace(day=1)
        span = (last - first).days + (1 if (y, m) == (today.year, today.month) else 0)
        row = f"| {month} | ${sum(xs):,.2f} | {len(xs)} | {len(xs) / span * 7:.1f} | ${statistics.mean(xs):,.2f} |"
        if cap:
            row += f" ${sum(xs) - cap:+,.2f} |"
        lines.append(row)

    by_payee = defaultdict(list)
    for r in rows:
        by_payee[r["payee"]].append(r["amount"])
    lines += ["", "## Top Merchants", "", "| Merchant | Purchases | Total | Average |", "|----------|----------:|------:|--------:|"]
    for payee, xs in sorted(by_payee.items(), key=lambda kv: -sum(kv[1]))[:15]:
        lines.append(f"| {payee} | {len(xs)} | ${sum(xs):,.2f} | ${statistics.mean(xs):,.2f} |")
    one_off = [xs for xs in by_payee.values() if len(xs) == 1]
    lines.append(f"\n{len(by_payee)} merchants; {len(one_off)} visited once (${sum(sum(xs) for xs in one_off):,.2f}).")

    weeks = days / 7
    by_dow = defaultdict(list)
    for r in rows:
        by_dow[date.fromisoformat(r["date"]).weekday()].append(r["amount"])
    lines += ["", "## By Weekday", "", "| Day | Purchases | Total | Per week | Average |", "|-----|----------:|------:|---------:|--------:|"]
    for i, day in enumerate(WEEKDAYS):
        xs = by_dow[i]
        avg = f"${statistics.mean(xs):,.2f}" if xs else "—"
        lines.append(f"| {day} | {len(xs)} | ${sum(xs):,.2f} | ${sum(xs) / weeks:,.2f} | {avg} |")

    content = "\n".join(lines) + "\n"
    save_report(f"{name.lower().replace(' ', '-')}-habits", content)
    return content


def main():
    parser = argparse.ArgumentParser(description="Purchase-level habits for one category")
    parser.add_argument("category", help="YNAB category name, e.g. 'Eating Out'")
    parser.add_argument("--since", default=f"{date.today().year}-01-01", help="start date (default: Jan 1 this year)")
    parser.add_argument("--cap", type=float, help="monthly cap to compare against")
    parser.add_argument("--json", dest="json_out", help="also write the purchase rows to this JSON file")
    args = parser.parse_args()
    print(analyze(args.category, args.since, args.cap, args.json_out))


if __name__ == "__main__":
    main()
