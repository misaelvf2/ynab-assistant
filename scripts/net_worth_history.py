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
    load_config, REPORTS_DIR
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


def generate_summary_block(monthly_data: list, total_change: int,
                           pct_change: float, avg_monthly_change: int,
                           months_back: int) -> str:
    """Generate structured summary data for the report."""
    lines = []

    first_nw = milliunits_to_dollars(monthly_data[0]["net_worth"])
    last_nw = milliunits_to_dollars(monthly_data[-1]["net_worth"])
    change = milliunits_to_dollars(total_change)
    avg = milliunits_to_dollars(avg_monthly_change)
    sign = "+" if change >= 0 else ""

    lines.append(f"- **Period:** {monthly_data[0]['month']} to {monthly_data[-1]['month']} ({months_back} months)")
    lines.append(f"- **Start:** ${first_nw:,.0f} → **End:** ${last_nw:,.0f}")
    lines.append(f"- **Total change:** {sign}${change:,.0f} ({sign}{pct_change:.1f}%)")
    lines.append(f"- **Avg monthly change:** {sign}${avg:,.0f}")

    changes = []
    for i in range(1, len(monthly_data)):
        c = monthly_data[i]["net_worth"] - monthly_data[i-1]["net_worth"]
        changes.append((monthly_data[i]["month"], c))

    if changes:
        best = max(changes, key=lambda x: x[1])
        worst = min(changes, key=lambda x: x[1])
        lines.append(f"- **Best month:** {best[0]} (+${milliunits_to_dollars(best[1]):,.0f})")
        lines.append(f"- **Worst month:** {worst[0]} (${milliunits_to_dollars(worst[1]):,.0f})")

    first_liab = milliunits_to_dollars(monthly_data[0]["liabilities"])
    last_liab = milliunits_to_dollars(monthly_data[-1]["liabilities"])
    liab_change = last_liab - first_liab
    liab_sign = "+" if liab_change >= 0 else ""
    lines.append(f"- **Debt change:** {liab_sign}${liab_change:,.0f}")

    return "\n".join(lines)


def generate_analysis(monthly_data: list, months_back: int) -> str:
    """Generate structured analysis data for the report."""
    import statistics
    lines = []

    first = monthly_data[0]
    last = monthly_data[-1]

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

    avg_gain = sum(c[1] for c in positive_months) / len(positive_months) if positive_months else 0
    avg_loss = sum(c[1] for c in negative_months) / len(negative_months) if negative_months else 0

    # Growth trajectory
    asset_growth = last_assets - first_assets
    asset_growth_pct = (asset_growth / first_assets * 100) if first_assets > 0 else 0
    liab_change = last_liab - first_liab
    liab_change_pct = (liab_change / first_liab * 100) if first_liab > 0 else 0

    if asset_growth >= 0 and liab_change <= 0:
        pattern = "ASSETS_UP_DEBT_DOWN"
    elif asset_growth >= 0 and liab_change > 0:
        pattern = "ASSETS_UP_DEBT_UP"
    elif asset_growth < 0 and liab_change <= 0:
        pattern = "ASSETS_DOWN_DEBT_DOWN"
    else:
        pattern = "ASSETS_DOWN_DEBT_UP"

    lines.append("### Growth Trajectory")
    lines.append("")
    lines.append(f"- Asset growth: ${first_assets:,.0f} → ${last_assets:,.0f} (+${asset_growth:,.0f}, {asset_growth_pct:+.1f}%)")
    liab_sign = "+" if liab_change >= 0 else ""
    lines.append(f"- Liability change: ${first_liab:,.0f} → ${last_liab:,.0f} ({liab_sign}${liab_change:,.0f}, {liab_change_pct:+.1f}%)")
    lines.append(f"- Pattern: {pattern}")
    lines.append("")

    # Consistency
    win_rate = len(positive_months) / len(changes) * 100 if changes else 0

    lines.append("### Consistency")
    lines.append("")
    lines.append(f"- Positive months: {len(positive_months)} / Negative months: {len(negative_months)} ({win_rate:.0f}% win rate)")
    lines.append(f"- Avg gain: +${milliunits_to_dollars(avg_gain):,.0f} / Avg loss: ${milliunits_to_dollars(avg_loss):,.0f}")

    if avg_gain > 0 and avg_loss < 0:
        gain_loss_ratio = abs(milliunits_to_dollars(avg_gain) / milliunits_to_dollars(avg_loss))
        lines.append(f"- Gain/loss ratio: {gain_loss_ratio:.1f}x")
    lines.append("")

    # Volatility
    change_values = [c[1] for c in changes]
    lines.append("### Volatility")
    lines.append("")
    if len(change_values) >= 2:
        try:
            stdev = statistics.stdev(change_values)
            mean = statistics.mean(change_values)
            stdev_dollars = milliunits_to_dollars(stdev)
            mean_dollars = milliunits_to_dollars(mean)

            if mean != 0:
                cv = abs(stdev / mean)
                if cv < 1:
                    vol_class = "LOW"
                elif cv < 2:
                    vol_class = "MODERATE"
                else:
                    vol_class = "HIGH"
            else:
                cv = 0
                vol_class = "N/A"

            lines.append(f"- Monthly stdev: ${stdev_dollars:,.0f}")
            lines.append(f"- Mean monthly change: ${mean_dollars:,.0f}")
            lines.append(f"- Coefficient of variation: {cv:.1f}")
            lines.append(f"- Classification: {vol_class}")
        except statistics.StatisticsError:
            lines.append("- Insufficient data")
    else:
        lines.append("- Insufficient data")
    lines.append("")

    # Notable months
    sorted_changes = sorted(changes, key=lambda x: x[1], reverse=True)
    top_3 = sorted_changes[:3]
    bottom_3 = sorted_changes[-3:]

    lines.append("### Notable Months")
    lines.append("")
    lines.append("**Best:**")
    for month, change in top_3:
        lines.append(f"- {month}: +${milliunits_to_dollars(change):,.0f}")
    lines.append("")
    lines.append("**Worst:**")
    for month, change in bottom_3:
        val = milliunits_to_dollars(change)
        sign = "+" if val >= 0 else ""
        lines.append(f"- {month}: {sign}${val:,.0f}")
    lines.append("")

    # Flag big swings as a data point
    best_month, best_change = sorted_changes[0]
    if best_change > 20000000:  # > $20k
        lines.append(f"**Large swing:** {best_month} (+${milliunits_to_dollars(best_change):,.0f})")
        lines.append("")

    # Forward look
    avg_monthly = sum(c[1] for c in changes) / len(changes) if changes else 0
    projected_12mo = last["net_worth"] + (avg_monthly * 12)
    projected_24mo = last["net_worth"] + (avg_monthly * 24)

    lines.append("### Forward Look")
    lines.append("")
    lines.append(f"- Avg monthly pace: ${milliunits_to_dollars(avg_monthly):,.0f}")
    lines.append(f"- Projected 12mo: ${milliunits_to_dollars(projected_12mo):,.0f}")
    lines.append(f"- Projected 24mo: ${milliunits_to_dollars(projected_24mo):,.0f}")

    # Milestone projections (from config.json, with sensible defaults)
    config = load_config()
    milestones = config.get("net_worth", {}).get("milestones", [])
    if not milestones:
        milestones = [350000, 400000, 500000, 750000, 1000000]

    current_nw_dollars = milliunits_to_dollars(last["net_worth"])
    avg_monthly_dollars = milliunits_to_dollars(avg_monthly)

    if avg_monthly_dollars > 0:
        for milestone in milestones:
            if milestone > current_nw_dollars:
                months_to_milestone = (milestone - current_nw_dollars) / avg_monthly_dollars
                if months_to_milestone <= 60:
                    years = months_to_milestone / 12
                    lines.append(f"- Next milestone: ${milestone/1000:.0f}k in ~{years:.1f} years")
                break

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

    summary_block = generate_summary_block(
        monthly_data, total_change, pct_change, avg_monthly_change, months_back
    )

    analysis = generate_analysis(monthly_data, months_back)

    lines = [
        f"# Net Worth History",
        f"",
        f"**Period:** {start_month} to {end_month} ({months_back} months)",
        f"**Generated:** {today}",
        f"",
        f"## Summary",
        f"",
        f"{summary_block}",
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
        f"## Analysis",
        f"",
        f"{analysis}",
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
