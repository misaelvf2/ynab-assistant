#!/usr/bin/env python3
"""
Spending Velocity - Track spending pace and project month-end totals
"""
import argparse
from datetime import date, timedelta
from calendar import monthrange
from ynab_client import (
    YNABClient, format_currency, milliunits_to_dollars,
    get_month_start_date, save_report
)


def get_category_history(client: YNABClient, category_id: str, months: int = 3) -> list:
    """Get historical spending for a category over past months."""
    today = date.today()
    history = []

    for i in range(1, months + 1):
        # Go back i months
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1

        month_str = f"{year}-{month:02d}-01"
        try:
            month_data = client.get_month(month_str)
            for cat_group in month_data.get('categories', []):
                if cat_group['id'] == category_id:
                    history.append({
                        'month': f"{year}-{month:02d}",
                        'budgeted': cat_group['budgeted'],
                        'activity': abs(cat_group['activity']),
                        'balance': cat_group['balance']
                    })
                    break
        except:
            pass

    return history


def analyze_velocity(threshold_pct: float = 10.0, alert_only: bool = False) -> str:
    """Analyze spending velocity across all categories."""
    client = YNABClient()
    today = date.today()

    # Calculate time progress through month
    days_in_month = monthrange(today.year, today.month)[1]
    days_elapsed = today.day
    time_pct = (days_elapsed / days_in_month) * 100
    days_remaining = days_in_month - days_elapsed

    # Get current month data
    month_str = get_month_start_date()
    month_data = client.get_month(month_str)

    categories = []

    # Categories are at top level in month data
    for cat in month_data.get('categories', []):
        if cat.get('hidden') or cat.get('deleted'):
            continue

        # Skip credit card categories (negative budgeted = payment tracking)
        if cat['budgeted'] < 0:
            continue

        budgeted = cat['budgeted']
        activity = abs(cat['activity']) if cat['activity'] < 0 else 0  # Only count outflows

        # Skip categories with no budget and no activity
        if budgeted == 0 and activity == 0:
            continue

        # Calculate velocity metrics
        if budgeted > 0:
            spent_pct = (activity / budgeted) * 100
            pace_diff = spent_pct - time_pct  # positive = ahead of pace (overspending)

            # Project month-end at current velocity
            if days_elapsed > 0:
                daily_rate = activity / days_elapsed
                projected = daily_rate * days_in_month
                projected_pct = (projected / budgeted) * 100
            else:
                projected = activity
                projected_pct = spent_pct

            remaining_budget = budgeted - activity
            daily_allowance = remaining_budget / days_remaining if days_remaining > 0 else 0
        else:
            # No budget set - still track spending
            spent_pct = 100 if activity > 0 else 0
            pace_diff = spent_pct
            projected = activity / days_elapsed * days_in_month if days_elapsed > 0 else activity
            projected_pct = 0
            remaining_budget = -activity
            daily_allowance = 0

        categories.append({
            'name': cat['name'],
            'group': cat.get('category_group_name', ''),
            'budgeted': budgeted,
            'activity': activity,
            'spent_pct': spent_pct,
            'time_pct': time_pct,
            'pace_diff': pace_diff,
            'projected': projected,
            'projected_pct': projected_pct,
            'remaining': remaining_budget,
            'daily_allowance': daily_allowance,
            'status': 'on_track'
        })

    # Classify status
    for cat in categories:
        if cat['budgeted'] == 0:
            cat['status'] = 'no_budget'
        elif cat['activity'] > cat['budgeted']:
            # Actually over budget
            cat['status'] = 'overspent'
        elif cat['activity'] == cat['budgeted']:
            # Exactly at budget - likely a fixed expense paid in full
            cat['status'] = 'fully_spent'
        elif cat['pace_diff'] >= threshold_pct:
            cat['status'] = 'warning'
        elif cat['pace_diff'] >= 0:
            cat['status'] = 'ahead'
        else:
            cat['status'] = 'on_track'

    # Sort by pace_diff descending (most overspent first)
    categories.sort(key=lambda x: x['pace_diff'], reverse=True)

    # Generate report
    overspent = [c for c in categories if c['status'] == 'overspent']
    warnings = [c for c in categories if c['status'] == 'warning']
    ahead = [c for c in categories if c['status'] == 'ahead']
    on_track = [c for c in categories if c['status'] == 'on_track']
    fully_spent = [c for c in categories if c['status'] == 'fully_spent']

    # Executive summary
    exec_lines = []
    exec_lines.append(
        f"Day {days_elapsed} of {days_in_month} ({time_pct:.0f}% through the month), "
        f"{days_remaining} days remaining."
    )

    if overspent:
        exec_lines.append(
            f"{len(overspent)} categories already overspent: "
            f"{', '.join(c['name'] for c in overspent[:3])}{'...' if len(overspent) > 3 else ''}."
        )

    if warnings:
        exec_lines.append(
            f"{len(warnings)} categories running hot (>{threshold_pct:.0f}% ahead of pace): "
            f"{', '.join(c['name'] for c in warnings[:3])}{'...' if len(warnings) > 3 else ''}."
        )

    if not overspent and not warnings:
        exec_lines.append("All categories on track or under pace. Disciplined month so far.")

    lines = [
        f"# Spending Velocity Report - {today}",
        f"",
        f"**Month:** {today.strftime('%B %Y')}",
        f"**Progress:** Day {days_elapsed} of {days_in_month} ({time_pct:.1f}%)",
        f"**Alert threshold:** {threshold_pct:.0f}% ahead of pace",
        f"",
        f"## Executive Summary",
        f"",
        f"{' '.join(exec_lines)}",
        f"",
    ]

    # Overspent categories
    if overspent:
        lines.extend([
            f"## Overspent ({len(overspent)})",
            f"",
            f"| Category | Budget | Spent | Over By |",
            f"|----------|--------|-------|---------|",
        ])
        for cat in overspent:
            over = cat['activity'] - cat['budgeted']
            lines.append(
                f"| {cat['name']} | {format_currency(cat['budgeted'])} | "
                f"{format_currency(cat['activity'])} | {format_currency(int(over))} |"
            )
        lines.append("")

    # Warning categories
    if warnings:
        lines.extend([
            f"## Running Hot ({len(warnings)})",
            f"",
            f"Categories spending faster than the calendar.",
            f"",
            f"| Category | Budget | Spent | Pace | Projected | Daily Allowance |",
            f"|----------|--------|-------|------|-----------|-----------------|",
        ])
        for cat in warnings:
            lines.append(
                f"| {cat['name']} | {format_currency(cat['budgeted'])} | "
                f"{format_currency(cat['activity'])} ({cat['spent_pct']:.0f}%) | "
                f"+{cat['pace_diff']:.0f}% | {format_currency(int(cat['projected']))} | "
                f"{format_currency(int(cat['daily_allowance']))}/day |"
            )
        lines.append("")

    if not alert_only:
        # Ahead but not warning
        if ahead:
            lines.extend([
                f"## Slightly Ahead ({len(ahead)})",
                f"",
                f"| Category | Budget | Spent | Pace |",
                f"|----------|--------|-------|------|",
            ])
            for cat in ahead[:10]:  # Limit to top 10
                lines.append(
                    f"| {cat['name']} | {format_currency(cat['budgeted'])} | "
                    f"{format_currency(cat['activity'])} ({cat['spent_pct']:.0f}%) | "
                    f"+{cat['pace_diff']:.0f}% |"
                )
            if len(ahead) > 10:
                lines.append(f"| *...and {len(ahead) - 10} more* | | | |")
            lines.append("")

        # On track
        if on_track:
            lines.extend([
                f"## On Track ({len(on_track)})",
                f"",
                f"| Category | Budget | Spent | Pace | Remaining |",
                f"|----------|--------|-------|------|-----------|",
            ])
            for cat in on_track[:10]:
                lines.append(
                    f"| {cat['name']} | {format_currency(cat['budgeted'])} | "
                    f"{format_currency(cat['activity'])} ({cat['spent_pct']:.0f}%) | "
                    f"{cat['pace_diff']:.0f}% | {format_currency(int(cat['remaining']))} |"
                )
            if len(on_track) > 10:
                lines.append(f"| *...and {len(on_track) - 10} more* | | | | |")
            lines.append("")

        # Fully spent (fixed expenses)
        if fully_spent:
            lines.extend([
                f"## Fixed Expenses Paid ({len(fully_spent)})",
                f"",
                f"*Monthly bills paid in full - no action needed.*",
                f"",
                f"| Category | Amount |",
                f"|----------|--------|",
            ])
            for cat in fully_spent:
                lines.append(f"| {cat['name']} | {format_currency(cat['budgeted'])} |")
            lines.append("")

    # Key categories quick check (eating out specifically)
    eating_out = next((c for c in categories if c['name'].lower() == 'eating out'), None)
    if eating_out:
        lines.extend([
            f"## Eating Out Watch",
            f"",
        ])
        if eating_out['status'] == 'overspent':
            lines.append(f"Already over budget. Stop eating out this month.")
        elif eating_out['status'] == 'warning':
            lines.append(
                f"Spent {format_currency(eating_out['activity'])} of {format_currency(eating_out['budgeted'])} "
                f"({eating_out['spent_pct']:.0f}%). "
                f"At this pace, you'll hit {format_currency(int(eating_out['projected']))} by month end. "
                f"Daily allowance: {format_currency(int(eating_out['daily_allowance']))}."
            )
        else:
            lines.append(
                f"Spent {format_currency(eating_out['activity'])} of {format_currency(eating_out['budgeted'])} "
                f"({eating_out['spent_pct']:.0f}%). On pace. "
                f"Daily allowance: {format_currency(int(eating_out['daily_allowance']))}."
            )
        lines.append("")

    lines.extend([
        f"---",
        f"",
        f"**Summary:** {len(overspent)} overspent, {len(warnings)} running hot, "
        f"{len(on_track)} on track, {len(fully_spent)} fixed expenses paid",
    ])

    report_content = "\n".join(lines)

    md_path, html_path = save_report("spending-velocity", report_content)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def main():
    parser = argparse.ArgumentParser(
        description="Analyze spending velocity and project month-end totals"
    )
    parser.add_argument(
        "--threshold", "-t", type=float, default=10.0,
        help="Alert threshold: flag categories this %% ahead of pace (default: 10)"
    )
    parser.add_argument(
        "--alerts-only", "-a", action="store_true",
        help="Only show overspent and warning categories"
    )
    args = parser.parse_args()

    analyze_velocity(threshold_pct=args.threshold, alert_only=args.alerts_only)


if __name__ == "__main__":
    main()
