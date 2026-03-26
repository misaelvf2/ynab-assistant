#!/usr/bin/env python3
"""
Net Worth History - Reconstruct and analyze historical net worth from transactions
"""
import argparse
import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from dateutil.relativedelta import relativedelta
from ynab_assistant import (
    YNABClient, format_currency, milliunits_to_dollars, save_report,
    REPORTS_DIR
)


def reconstruct_account_history(account: dict, transactions: list) -> dict:
    """Reconstruct historical month-end balances for an account."""
    current_balance = account["balance"]

    txns_by_month = defaultdict(list)
    for txn in transactions:
        if txn["deleted"]:
            continue
        month = txn["date"][:7]
        txns_by_month[month].append(txn)

    if not txns_by_month:
        return {}

    months = sorted(txns_by_month.keys())
    first_month = months[0]

    start = datetime.strptime(first_month, "%Y-%m")
    end = datetime.now()
    all_months = []
    current = start
    while current <= end:
        all_months.append(current.strftime("%Y-%m"))
        current += relativedelta(months=1)

    balances = {}
    running_balance = current_balance

    for month in reversed(all_months):
        balances[month] = running_balance
        for txn in txns_by_month.get(month, []):
            running_balance -= txn["amount"]

    return balances


def generate_executive_summary(monthly_data: list, total_change: int,
                                pct_change: float, avg_monthly_change: int,
                                months_back: int) -> str:
    """Generate plain-English executive summary."""
    lines = []

    first_nw = milliunits_to_dollars(monthly_data[0]["net_worth"])
    last_nw = milliunits_to_dollars(monthly_data[-1]["net_worth"])
    change = milliunits_to_dollars(total_change)
    avg = milliunits_to_dollars(avg_monthly_change)

    if pct_change > 50:
        lines.append(
            f"Over the past {months_back} months, your net worth has grown from ${first_nw:,.0f} to "
            f"${last_nw:,.0f}—a gain of ${change:,.0f} ({pct_change:+.1f}%). That's serious progress."
        )
    elif pct_change > 20:
        lines.append(
            f"Net worth grew from ${first_nw:,.0f} to ${last_nw:,.0f} over {months_back} months, "
            f"up ${change:,.0f} ({pct_change:+.1f}%). Solid trajectory."
        )
    elif pct_change > 0:
        lines.append(
            f"You've added ${change:,.0f} to your net worth over {months_back} months ({pct_change:+.1f}%). "
            f"Positive, but not spectacular."
        )
    elif pct_change > -10:
        lines.append(
            f"Net worth is roughly flat over {months_back} months—${change:,.0f} change ({pct_change:+.1f}%). "
            f"You're treading water."
        )
    else:
        lines.append(
            f"Net worth declined from ${first_nw:,.0f} to ${last_nw:,.0f}, "
            f"down ${abs(change):,.0f} ({pct_change:.1f}%). Time to diagnose what went wrong."
        )

    if avg > 0:
        lines.append(f"Average monthly gain: ${avg:,.0f}.")
    else:
        lines.append(f"Average monthly change: ${avg:,.0f}.")

    changes = []
    for i in range(1, len(monthly_data)):
        c = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
        changes.append((monthly_data[i]["month"], c))

    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])

        best_val = milliunits_to_dollars(best[1])
        worst_val = milliunits_to_dollars(worst[1])

        if best[1] > 0:
            lines.append(f"Best month: {best[0]} (+${best_val:,.0f}).")
        if worst[1] < 0:
            lines.append(f"Worst month: {worst[0]} (${worst_val:,.0f}).")

    first_liab = milliunits_to_dollars(monthly_data[0]["liabilities"])
    last_liab = milliunits_to_dollars(monthly_data[-1]["liabilities"])
    liab_change = last_liab - first_liab

    if liab_change < -5000:
        lines.append(f"Debt reduced by ${abs(liab_change):,.0f}—good work paying things down.")
    elif liab_change > 5000:
        lines.append(f"Debt increased by ${liab_change:,.0f}. Keep an eye on that.")

    return " ".join(lines)


def generate_discussion(monthly_data: list, months_back: int) -> str:
    """Generate in-depth discussion of the numbers."""
    lines = []

    # Calculate various metrics
    first = monthly_data[0]
    last = monthly_data[-1]

    first_nw = milliunits_to_dollars(first["net_worth"])
    last_nw = milliunits_to_dollars(last["net_worth"])
    first_assets = milliunits_to_dollars(first["assets"])
    last_assets = milliunits_to_dollars(last["assets"])
    first_liab = milliunits_to_dollars(first["liabilities"])
    last_liab = milliunits_to_dollars(last["liabilities"])

    # Monthly changes
    changes = []
    for i in range(1, len(monthly_data)):
        c = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
        changes.append((monthly_data[i]["month"], c))

    positive_months = [c for c in changes if c[1] > 0]
    negative_months = [c for c in changes if c[1] < 0]
    flat_months = [c for c in changes if c[1] == 0]

    avg_gain = sum(c[1] for c in positive_months) / len(positive_months) if positive_months else 0
    avg_loss = sum(c[1] for c in negative_months) / len(negative_months) if negative_months else 0

    # Growth rate analysis
    lines.append("### Growth Trajectory")
    lines.append("")

    asset_growth = last_assets - first_assets
    asset_growth_pct = (asset_growth / first_assets * 100) if first_assets > 0 else 0
    liab_change = last_liab - first_liab
    liab_change_pct = (liab_change / first_liab * 100) if first_liab > 0 else 0

    lines.append(
        f"Assets grew from ${first_assets:,.0f} to ${last_assets:,.0f}, "
        f"an increase of ${asset_growth:,.0f} ({asset_growth_pct:+.1f}%). "
    )

    if liab_change < 0:
        lines.append(
            f"Meanwhile, liabilities dropped from ${first_liab:,.0f} to ${last_liab:,.0f}, "
            f"a reduction of ${abs(liab_change):,.0f} ({liab_change_pct:.1f}%). "
            f"This double effect—assets up, debt down—is the ideal wealth-building pattern."
        )
    else:
        lines.append(
            f"Liabilities increased from ${first_liab:,.0f} to ${last_liab:,.0f} (+${liab_change:,.0f}). "
            f"Net worth still grew because asset gains outpaced debt accumulation, but watch this trend."
        )

    lines.append("")

    # Consistency analysis
    lines.append("### Consistency")
    lines.append("")

    win_rate = len(positive_months) / len(changes) * 100 if changes else 0
    lines.append(
        f"Out of {len(changes)} months, {len(positive_months)} were positive and {len(negative_months)} were negative "
        f"({win_rate:.0f}% win rate). "
    )

    if avg_gain > 0 and avg_loss < 0:
        gain_loss_ratio = abs(milliunits_to_dollars(avg_gain) / milliunits_to_dollars(avg_loss))
        lines.append(
            f"Average winning month: +${milliunits_to_dollars(avg_gain):,.0f}. "
            f"Average losing month: ${milliunits_to_dollars(avg_loss):,.0f}. "
            f"Your gains are {gain_loss_ratio:.1f}x your losses on average—"
        )
        if gain_loss_ratio > 2:
            lines.append("that's a healthy asymmetry.")
        elif gain_loss_ratio > 1:
            lines.append("acceptable, but there's room for more upside capture.")
        else:
            lines.append("you're losing more on bad months than you gain on good ones. Not ideal.")

    lines.append("")

    # Volatility analysis
    lines.append("### Volatility")
    lines.append("")

    change_values = [c[1] for c in changes]
    if change_values:
        import statistics
        try:
            stdev = statistics.stdev(change_values)
            mean = statistics.mean(change_values)
            stdev_dollars = milliunits_to_dollars(stdev)
            mean_dollars = milliunits_to_dollars(mean)

            lines.append(
                f"Monthly change standard deviation: ${stdev_dollars:,.0f}. "
                f"Mean monthly change: ${mean_dollars:,.0f}. "
            )

            # Coefficient of variation (relative volatility)
            if mean != 0:
                cv = abs(stdev / mean)
                if cv < 1:
                    lines.append(
                        f"Volatility is relatively low compared to average gains—your growth is fairly steady."
                    )
                elif cv < 2:
                    lines.append(
                        f"Moderate volatility. Expect some months to deviate significantly from the average."
                    )
                else:
                    lines.append(
                        f"High volatility. Your month-to-month swings are large relative to average growth."
                    )
        except statistics.StatisticsError:
            pass

    lines.append("")

    # Outlier analysis
    lines.append("### Notable Months")
    lines.append("")

    sorted_changes = sorted(changes, key=lambda x: x[1], reverse=True)
    top_3 = sorted_changes[:3]
    bottom_3 = sorted_changes[-3:]

    lines.append("**Best months:**")
    for month, change in top_3:
        lines.append(f"- {month}: +${milliunits_to_dollars(change):,.0f}")

    lines.append("")
    lines.append("**Worst months:**")
    for month, change in bottom_3:
        val = milliunits_to_dollars(change)
        sign = "+" if val >= 0 else ""
        lines.append(f"- {month}: {sign}${val:,.0f}")

    lines.append("")

    # Big swings deserve explanation
    best_month, best_change = sorted_changes[0]
    if best_change > 20000000:  # > $20k
        lines.append(
            f"The {best_month} spike of +${milliunits_to_dollars(best_change):,.0f} stands out. "
            f"This was likely a major event: property equity recorded, large bonus, or exceptional market month. "
            f"Worth noting because it's not replicable every month."
        )
        lines.append("")

    # Projected future
    lines.append("### Forward Look")
    lines.append("")

    avg_monthly = sum(c[1] for c in changes) / len(changes) if changes else 0
    projected_12mo = last["net_worth"] + (avg_monthly * 12)
    projected_24mo = last["net_worth"] + (avg_monthly * 24)

    lines.append(
        f"At the current average pace of ${milliunits_to_dollars(avg_monthly):,.0f}/month, "
        f"you'd reach ${milliunits_to_dollars(projected_12mo):,.0f} in 12 months "
        f"and ${milliunits_to_dollars(projected_24mo):,.0f} in 24 months. "
    )

    # Milestone projections
    milestones = [350000, 400000, 500000, 750000, 1000000]
    current_nw_dollars = milliunits_to_dollars(last["net_worth"])
    avg_monthly_dollars = milliunits_to_dollars(avg_monthly)

    for milestone in milestones:
        if milestone > current_nw_dollars and avg_monthly_dollars > 0:
            months_to_milestone = (milestone - current_nw_dollars) / avg_monthly_dollars
            if months_to_milestone <= 60:  # Within 5 years
                years = months_to_milestone / 12
                lines.append(
                    f"At this pace, you'd hit ${milestone/1000:.0f}k in roughly {years:.1f} years."
                )
                break

    lines.append("")
    lines.append(
        "These projections assume consistent contributions and average market returns. "
        "Reality will vary—but the trajectory is yours to maintain."
    )

    return "\n".join(lines)


def generate_html_with_charts(report_content: str, monthly_data: list, base_filename: str) -> Path:
    """Generate HTML report with embedded Chart.js graphs."""
    import markdown

    # Prepare chart data
    labels = [d["month"] for d in monthly_data]
    net_worth_data = [round(milliunits_to_dollars(d["net_worth"]), 2) for d in monthly_data]
    assets_data = [round(milliunits_to_dollars(d["assets"]), 2) for d in monthly_data]
    liabilities_data = [round(milliunits_to_dollars(d["liabilities"]), 2) for d in monthly_data]

    # Calculate monthly changes for slope visualization
    changes_data = [0]  # First month has no prior
    for i in range(1, len(monthly_data)):
        change = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
        changes_data.append(round(milliunits_to_dollars(change), 2))

    # Calculate 3-month rolling average
    rolling_avg = []
    for i in range(len(net_worth_data)):
        if i < 2:
            rolling_avg.append(net_worth_data[i])
        else:
            avg = (net_worth_data[i] + net_worth_data[i-1] + net_worth_data[i-2]) / 3
            rolling_avg.append(round(avg, 2))

    # Convert markdown to HTML
    html_content = markdown.markdown(report_content, extensions=['tables', 'fenced_code'])

    html_full = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Net Worth History Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            max-width: 1100px;
            margin: 40px auto;
            padding: 20px;
            line-height: 1.6;
            color: #333;
        }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        h3 {{ color: #7f8c8d; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 14px; }}
        th, td {{ border: 1px solid #ddd; padding: 10px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .chart-container {{
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            padding: 20px;
            margin: 30px 0;
        }}
        .chart-title {{
            font-size: 18px;
            font-weight: 600;
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        .charts-grid {{
            display: grid;
            grid-template-columns: 1fr;
            gap: 30px;
        }}
        canvas {{ max-height: 400px; }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 30px 0; }}
        strong {{ color: #2c3e50; }}
        p {{ margin: 1em 0; }}
    </style>
</head>
<body>

<div class="charts-grid">
    <div class="chart-container">
        <div class="chart-title">Net Worth Over Time</div>
        <canvas id="netWorthChart"></canvas>
    </div>

    <div class="chart-container">
        <div class="chart-title">Assets vs Liabilities</div>
        <canvas id="assetsLiabChart"></canvas>
    </div>

    <div class="chart-container">
        <div class="chart-title">Monthly Change (Growth Rate)</div>
        <canvas id="changesChart"></canvas>
    </div>
</div>

<hr>

{html_content}

<script>
const labels = {json.dumps(labels)};
const netWorthData = {json.dumps(net_worth_data)};
const assetsData = {json.dumps(assets_data)};
const liabilitiesData = {json.dumps(liabilities_data)};
const changesData = {json.dumps(changes_data)};
const rollingAvg = {json.dumps(rolling_avg)};

// Net Worth Chart
new Chart(document.getElementById('netWorthChart'), {{
    type: 'line',
    data: {{
        labels: labels,
        datasets: [{{
            label: 'Net Worth',
            data: netWorthData,
            borderColor: '#3498db',
            backgroundColor: 'rgba(52, 152, 219, 0.1)',
            fill: true,
            tension: 0.3,
            pointRadius: 4,
            pointHoverRadius: 6
        }}, {{
            label: '3-Month Rolling Avg',
            data: rollingAvg,
            borderColor: '#e74c3c',
            borderDash: [5, 5],
            fill: false,
            tension: 0.3,
            pointRadius: 0
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ position: 'top' }},
            tooltip: {{
                callbacks: {{
                    label: function(context) {{
                        return context.dataset.label + ': $' + context.raw.toLocaleString();
                    }}
                }}
            }}
        }},
        scales: {{
            y: {{
                beginAtZero: false,
                ticks: {{
                    callback: function(value) {{
                        return '$' + (value / 1000).toFixed(0) + 'k';
                    }}
                }}
            }}
        }}
    }}
}});

// Assets vs Liabilities Chart
new Chart(document.getElementById('assetsLiabChart'), {{
    type: 'line',
    data: {{
        labels: labels,
        datasets: [{{
            label: 'Assets',
            data: assetsData,
            borderColor: '#27ae60',
            backgroundColor: 'rgba(39, 174, 96, 0.1)',
            fill: true,
            tension: 0.3
        }}, {{
            label: 'Liabilities',
            data: liabilitiesData,
            borderColor: '#e74c3c',
            backgroundColor: 'rgba(231, 76, 60, 0.1)',
            fill: true,
            tension: 0.3
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ position: 'top' }},
            tooltip: {{
                callbacks: {{
                    label: function(context) {{
                        return context.dataset.label + ': $' + context.raw.toLocaleString();
                    }}
                }}
            }}
        }},
        scales: {{
            y: {{
                beginAtZero: true,
                ticks: {{
                    callback: function(value) {{
                        return '$' + (value / 1000).toFixed(0) + 'k';
                    }}
                }}
            }}
        }}
    }}
}});

// Monthly Changes Chart
new Chart(document.getElementById('changesChart'), {{
    type: 'bar',
    data: {{
        labels: labels,
        datasets: [{{
            label: 'Monthly Change',
            data: changesData,
            backgroundColor: changesData.map(v => v >= 0 ? 'rgba(39, 174, 96, 0.7)' : 'rgba(231, 76, 60, 0.7)'),
            borderColor: changesData.map(v => v >= 0 ? '#27ae60' : '#e74c3c'),
            borderWidth: 1
        }}]
    }},
    options: {{
        responsive: true,
        plugins: {{
            legend: {{ display: false }},
            tooltip: {{
                callbacks: {{
                    label: function(context) {{
                        const val = context.raw;
                        const sign = val >= 0 ? '+' : '';
                        return sign + '$' + val.toLocaleString();
                    }}
                }}
            }}
        }},
        scales: {{
            y: {{
                ticks: {{
                    callback: function(value) {{
                        const sign = value >= 0 ? '+' : '';
                        return sign + '$' + (value / 1000).toFixed(0) + 'k';
                    }}
                }}
            }}
        }}
    }}
}});
</script>

</body>
</html>"""

    REPORTS_DIR.mkdir(exist_ok=True)
    html_path = REPORTS_DIR / f"{base_filename}.html"
    with open(html_path, "w") as f:
        f.write(html_full)

    return html_path


def calculate_net_worth_history(months_back: int = 24) -> str:
    """Calculate net worth history for the last N months"""
    client = YNABClient()
    accounts = client.get_accounts()
    today = date.today()

    print("Fetching transaction history (this may take a moment)...")

    all_account_histories = {}

    for acc in accounts:
        if acc["closed"] or acc["deleted"]:
            continue

        txns = client.get_account_transactions(acc["id"])
        history = reconstruct_account_history(acc, txns)
        if history:
            all_account_histories[acc["id"]] = {
                "name": acc["name"],
                "type": acc["type"],
                "on_budget": acc["on_budget"],
                "history": history
            }

    end_month = today.strftime("%Y-%m")
    start_date = today - relativedelta(months=months_back)
    start_month = start_date.strftime("%Y-%m")

    months = []
    current = start_date
    while current.strftime("%Y-%m") <= end_month:
        months.append(current.strftime("%Y-%m"))
        current += relativedelta(months=1)

    monthly_data = []

    for month in months:
        assets = 0
        liabilities = 0

        for acc_id, acc_data in all_account_histories.items():
            balance = acc_data["history"].get(month, 0)

            if balance >= 0:
                assets += balance
            else:
                liabilities += abs(balance)

        net_worth = assets - liabilities
        monthly_data.append({
            "month": month,
            "assets": assets,
            "liabilities": liabilities,
            "net_worth": net_worth
        })

    if len(monthly_data) >= 2:
        first = monthly_data[0]
        last = monthly_data[-1]
        total_change = last["net_worth"] - first["net_worth"]
        pct_change = (total_change / first["net_worth"] * 100) if first["net_worth"] != 0 else 0

        monthly_changes = []
        for i in range(1, len(monthly_data)):
            change = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
            monthly_changes.append(change)
        avg_monthly_change = sum(monthly_changes) // len(monthly_changes) if monthly_changes else 0
    else:
        total_change = 0
        pct_change = 0
        avg_monthly_change = 0

    exec_summary = generate_executive_summary(
        monthly_data, total_change, pct_change, avg_monthly_change, months_back
    )

    discussion = generate_discussion(monthly_data, months_back)

    lines = [
        f"# Net Worth History",
        f"",
        f"**Period:** {start_month} to {end_month} ({months_back} months)",
        f"**Generated:** {today}",
        f"",
        f"## Executive Summary",
        f"",
        f"{exec_summary}",
        f"",
        f"## Key Metrics",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Starting Net Worth ({start_month}) | {format_currency(monthly_data[0]['net_worth'])} |",
        f"| Current Net Worth ({end_month}) | {format_currency(monthly_data[-1]['net_worth'])} |",
        f"| Total Change | {'+' if total_change >= 0 else ''}{format_currency(total_change)} |",
        f"| Percentage Change | {'+' if pct_change >= 0 else ''}{pct_change:.1f}% |",
        f"| Avg Monthly Change | {'+' if avg_monthly_change >= 0 else ''}{format_currency(avg_monthly_change)} |",
        f"",
        f"## Discussion",
        f"",
        f"{discussion}",
        f"",
        f"## Monthly Breakdown",
        f"",
        f"| Month | Assets | Liabilities | Net Worth | Change |",
        f"|-------|--------|-------------|-----------|--------|",
    ]

    prev_nw = None
    for data in monthly_data:
        if prev_nw is not None:
            change = data["net_worth"] - prev_nw
            change_str = f"{'+' if change >= 0 else ''}{format_currency(change)}"
        else:
            change_str = "-"

        lines.append(
            f"| {data['month']} | {format_currency(data['assets'])} | "
            f"{format_currency(data['liabilities'])} | {format_currency(data['net_worth'])} | "
            f"{change_str} |"
        )
        prev_nw = data["net_worth"]

    if len(monthly_data) >= 13:
        lines.extend([
            f"",
            f"## Year-over-Year",
            f"",
            f"| Month | This Year | Last Year | YoY Change |",
            f"|-------|-----------|-----------|------------|",
        ])

        for i in range(len(monthly_data) - 12, len(monthly_data)):
            if i >= 12:
                current = monthly_data[i]
                previous = monthly_data[i - 12]
                yoy_change = current["net_worth"] - previous["net_worth"]
                yoy_pct = (yoy_change / previous["net_worth"] * 100) if previous["net_worth"] != 0 else 0

                lines.append(
                    f"| {current['month']} | {format_currency(current['net_worth'])} | "
                    f"{format_currency(previous['net_worth'])} | "
                    f"{'+' if yoy_change >= 0 else ''}{format_currency(yoy_change)} ({'+' if yoy_pct >= 0 else ''}{yoy_pct:.1f}%) |"
                )

    lines.extend([
        f"",
        f"---",
        f"",
        f"*API calls: {client.cache_stats['misses']} fresh, {client.cache_stats['hits']} cached*",
    ])

    report_content = "\n".join(lines)

    # Save markdown
    REPORTS_DIR.mkdir(exist_ok=True)
    base_filename = f"{today.isoformat()}_net-worth-history"
    md_path = REPORTS_DIR / f"{base_filename}.md"
    with open(md_path, "w") as f:
        f.write(report_content)

    # Generate HTML with charts
    html_path = generate_html_with_charts(report_content, monthly_data, base_filename)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Analyze net worth history")
    parser.add_argument("--months", "-m", type=int, default=24,
                        help="Number of months to analyze (default: 24)")
    args = parser.parse_args()

    calculate_net_worth_history(months_back=args.months)


if __name__ == "__main__":
    main()
