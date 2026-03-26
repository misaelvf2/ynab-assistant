#!/usr/bin/env python3
"""
Data Service - Unified data layer for dashboard
Returns structured dicts instead of markdown strings
"""
from datetime import date, timedelta
from calendar import monthrange
from collections import defaultdict
from dateutil.relativedelta import relativedelta
from ynab_assistant import (
    YNABClient, load_config, milliunits_to_dollars,
    get_month_start_date
)


def get_net_worth_data() -> dict:
    """Get current net worth breakdown."""
    client = YNABClient()
    accounts = client.get_accounts()

    assets = {"on_budget": [], "tracking": []}
    liabilities = {"credit_cards": [], "loans": []}

    for acc in accounts:
        if acc["closed"] or acc["deleted"]:
            continue

        balance = acc["balance"]
        entry = {
            "name": acc["name"],
            "balance": milliunits_to_dollars(balance),
            "balance_raw": balance,
            "type": acc["type"]
        }

        if balance >= 0:
            if acc["on_budget"]:
                assets["on_budget"].append(entry)
            else:
                assets["tracking"].append(entry)
        else:
            if acc["type"] == "creditCard":
                liabilities["credit_cards"].append(entry)
            else:
                liabilities["loans"].append(entry)

    total_on_budget = sum(a["balance_raw"] for a in assets["on_budget"])
    total_tracking = sum(a["balance_raw"] for a in assets["tracking"])
    total_assets = total_on_budget + total_tracking

    total_credit = sum(abs(l["balance_raw"]) for l in liabilities["credit_cards"])
    total_loans = sum(abs(l["balance_raw"]) for l in liabilities["loans"])
    total_liabilities = total_credit + total_loans

    net_worth = total_assets - total_liabilities

    return {
        "net_worth": milliunits_to_dollars(net_worth),
        "net_worth_raw": net_worth,
        "total_assets": milliunits_to_dollars(total_assets),
        "total_liabilities": milliunits_to_dollars(total_liabilities),
        "assets": {
            "on_budget": sorted(assets["on_budget"], key=lambda x: -x["balance_raw"]),
            "tracking": sorted(assets["tracking"], key=lambda x: -x["balance_raw"]),
            "total_on_budget": milliunits_to_dollars(total_on_budget),
            "total_tracking": milliunits_to_dollars(total_tracking)
        },
        "liabilities": {
            "credit_cards": sorted(liabilities["credit_cards"], key=lambda x: x["balance_raw"]),
            "loans": sorted(liabilities["loans"], key=lambda x: x["balance_raw"]),
            "total_credit": milliunits_to_dollars(total_credit),
            "total_loans": milliunits_to_dollars(total_loans)
        }
    }


def get_net_worth_history(months: int = 12) -> dict:
    """Get historical net worth data for charts."""
    client = YNABClient()
    today = date.today()
    accounts = client.get_accounts()

    # Build account lookup
    account_map = {acc["id"]: acc for acc in accounts if not acc["deleted"]}

    # Get all transactions
    start_date = today - relativedelta(months=months)
    all_transactions = client.get_transactions(since_date=start_date.strftime("%Y-%m-%d"))

    # Current balances
    current_balances = {acc_id: acc["balance"] for acc_id, acc in account_map.items()}

    # Generate month list
    month_list = []
    for i in range(months, -1, -1):
        d = today - relativedelta(months=i)
        month_list.append(d.strftime("%Y-%m"))

    # Work backwards from current balances
    monthly_data = []
    working_balances = current_balances.copy()

    for month_str in reversed(month_list):
        year, month = int(month_str[:4]), int(month_str[5:7])
        month_end = date(year, month, monthrange(year, month)[1])

        if month_str == today.strftime("%Y-%m"):
            month_end = today

        # Calculate totals
        total_assets = 0
        total_liabilities = 0

        for acc_id, balance in working_balances.items():
            acc = account_map.get(acc_id)
            if not acc or acc["closed"]:
                continue
            if balance >= 0:
                total_assets += balance
            else:
                total_liabilities += abs(balance)

        net_worth = total_assets - total_liabilities

        monthly_data.append({
            "month": month_str,
            "net_worth": milliunits_to_dollars(net_worth),
            "assets": milliunits_to_dollars(total_assets),
            "liabilities": milliunits_to_dollars(total_liabilities)
        })

        # Reverse transactions for this month
        month_txns = [
            t for t in all_transactions
            if t["date"].startswith(month_str) and not t["deleted"]
        ]

        for txn in month_txns:
            acc_id = txn["account_id"]
            if acc_id in working_balances:
                working_balances[acc_id] -= txn["amount"]

    monthly_data.reverse()

    # Calculate changes
    for i, data in enumerate(monthly_data):
        if i == 0:
            data["change"] = 0
        else:
            data["change"] = data["net_worth"] - monthly_data[i-1]["net_worth"]

    return {
        "months": monthly_data,
        "start_net_worth": monthly_data[0]["net_worth"] if monthly_data else 0,
        "current_net_worth": monthly_data[-1]["net_worth"] if monthly_data else 0,
        "total_change": monthly_data[-1]["net_worth"] - monthly_data[0]["net_worth"] if len(monthly_data) > 1 else 0
    }


def get_eating_out_data(year: int = None, month: int = None) -> dict:
    """Get eating out tracker data."""
    client = YNABClient()
    config = load_config()
    today = date.today()

    if year is None:
        year = today.year
    if month is None:
        month = today.month

    eating_out_config = config.get("spending_caps", {}).get("eating_out", {})
    hard_cap = eating_out_config.get("monthly_limit", 600)
    category_id = eating_out_config.get("category_id")

    month_str = f"{year}-{month:02d}-01"
    category_data = client.get_category_by_month(category_id, month_str)

    activity = abs(category_data.get("activity", 0))
    budgeted = category_data.get("budgeted", 0)

    spent = milliunits_to_dollars(activity)
    remaining = hard_cap - spent

    # Pace calculations
    days_in_month = monthrange(year, month)[1]
    is_current_month = (year == today.year and month == today.month)

    if is_current_month:
        days_elapsed = today.day
        days_remaining = days_in_month - days_elapsed
    else:
        days_elapsed = days_in_month
        days_remaining = 0

    daily_avg = spent / days_elapsed if days_elapsed > 0 else 0
    projected = daily_avg * days_in_month
    daily_allowance = remaining / days_remaining if days_remaining > 0 else 0

    # Status
    if spent > hard_cap:
        status = "over"
    elif projected > hard_cap:
        status = "warning"
    elif spent > hard_cap * 0.8:
        status = "caution"
    else:
        status = "on_track"

    return {
        "spent": spent,
        "hard_cap": hard_cap,
        "budgeted": milliunits_to_dollars(budgeted),
        "remaining": remaining,
        "days_elapsed": days_elapsed,
        "days_remaining": days_remaining,
        "days_in_month": days_in_month,
        "daily_avg": daily_avg,
        "projected": projected,
        "daily_allowance": daily_allowance,
        "status": status,
        "percent_used": (spent / hard_cap * 100) if hard_cap > 0 else 0,
        "percent_month": (days_elapsed / days_in_month * 100)
    }


def get_spending_velocity_data(threshold_pct: float = 10.0) -> dict:
    """Get spending velocity for all categories."""
    client = YNABClient()
    today = date.today()

    days_in_month = monthrange(today.year, today.month)[1]
    days_elapsed = today.day
    time_pct = (days_elapsed / days_in_month) * 100
    days_remaining = days_in_month - days_elapsed

    month_str = get_month_start_date()
    month_data = client.get_month(month_str)

    categories = []

    for cat in month_data.get("categories", []):
        if cat.get("hidden") or cat.get("deleted"):
            continue
        if cat["budgeted"] < 0:  # Skip credit card categories
            continue

        budgeted = cat["budgeted"]
        activity = abs(cat["activity"]) if cat["activity"] < 0 else 0

        if budgeted == 0 and activity == 0:
            continue

        if budgeted > 0:
            spent_pct = (activity / budgeted) * 100
            pace_diff = spent_pct - time_pct
            daily_rate = activity / days_elapsed if days_elapsed > 0 else 0
            projected = daily_rate * days_in_month
            remaining = budgeted - activity
            daily_allowance = remaining / days_remaining if days_remaining > 0 else 0
        else:
            spent_pct = 100 if activity > 0 else 0
            pace_diff = spent_pct
            projected = activity
            remaining = -activity
            daily_allowance = 0

        # Classify status
        if budgeted == 0:
            status = "no_budget"
        elif activity > budgeted:
            status = "overspent"
        elif activity == budgeted:
            status = "fully_spent"
        elif pace_diff >= threshold_pct:
            status = "warning"
        elif pace_diff >= 0:
            status = "ahead"
        else:
            status = "on_track"

        categories.append({
            "name": cat["name"],
            "budgeted": milliunits_to_dollars(budgeted),
            "spent": milliunits_to_dollars(activity),
            "spent_pct": spent_pct,
            "pace_diff": pace_diff,
            "projected": milliunits_to_dollars(projected),
            "remaining": milliunits_to_dollars(remaining),
            "daily_allowance": milliunits_to_dollars(daily_allowance),
            "status": status
        })

    categories.sort(key=lambda x: x["pace_diff"], reverse=True)

    return {
        "day": days_elapsed,
        "days_in_month": days_in_month,
        "days_remaining": days_remaining,
        "time_pct": time_pct,
        "threshold_pct": threshold_pct,
        "categories": categories,
        "overspent": [c for c in categories if c["status"] == "overspent"],
        "warning": [c for c in categories if c["status"] == "warning"],
        "on_track": [c for c in categories if c["status"] == "on_track"],
        "fully_spent": [c for c in categories if c["status"] == "fully_spent"]
    }


def get_transaction_issues(days: int = 30, memo_threshold: float = 100) -> dict:
    """Get transactions needing attention."""
    client = YNABClient()
    today = date.today()
    since = today - timedelta(days=days)

    transactions = client.get_transactions(since_date=since.strftime("%Y-%m-%d"))

    txns = [
        t for t in transactions
        if not t["deleted"] and t["transfer_account_id"] is None
    ]

    uncategorized = []
    missing_memo = []
    unapproved = []

    memo_threshold_mu = int(memo_threshold * 1000)

    for txn in txns:
        amount = txn["amount"]
        abs_amount = abs(amount)

        txn_data = {
            "id": txn["id"],
            "date": txn["date"],
            "payee": txn["payee_name"],
            "amount": milliunits_to_dollars(amount),
            "category": txn["category_name"],
            "account": txn["account_name"],
            "memo": txn["memo"]
        }

        if txn["category_name"] == "Uncategorized" or txn["category_id"] is None:
            if amount < 0:
                uncategorized.append(txn_data)

        if abs_amount >= memo_threshold_mu and not txn["memo"]:
            missing_memo.append(txn_data)

        if not txn["approved"]:
            unapproved.append(txn_data)

    return {
        "total_reviewed": len(txns),
        "days": days,
        "uncategorized": uncategorized,
        "missing_memo": missing_memo,
        "unapproved": unapproved,
        "total_issues": len(uncategorized) + len(missing_memo) + len(unapproved)
    }


def get_dashboard_summary() -> dict:
    """Unified data for dashboard - all key metrics."""
    from datetime import datetime

    net_worth = get_net_worth_data()
    eating_out = get_eating_out_data()
    velocity = get_spending_velocity_data()
    issues = get_transaction_issues(days=14)
    history = get_net_worth_history(months=12)

    # Calculate month-over-month change
    if len(history["months"]) >= 2:
        current = history["months"][-1]["net_worth"]
        previous = history["months"][-2]["net_worth"]
        mom_change = current - previous
        mom_pct = (mom_change / previous * 100) if previous != 0 else 0
    else:
        mom_change = 0
        mom_pct = 0

    return {
        "generated_at": datetime.now().isoformat(),
        "net_worth": {
            "current": net_worth["net_worth"],
            "total_assets": net_worth["total_assets"],
            "total_liabilities": net_worth["total_liabilities"],
            "mom_change": mom_change,
            "mom_pct": mom_pct
        },
        "eating_out": eating_out,
        "velocity": {
            "day": velocity["day"],
            "days_in_month": velocity["days_in_month"],
            "time_pct": velocity["time_pct"],
            "overspent_count": len(velocity["overspent"]),
            "warning_count": len(velocity["warning"]),
            "overspent": velocity["overspent"],
            "warning": velocity["warning"]
        },
        "alerts": {
            "uncategorized": len(issues["uncategorized"]),
            "unapproved": len(issues["unapproved"]),
            "missing_memo": len(issues["missing_memo"]),
            "total": issues["total_issues"]
        },
        "history": history["months"]
    }


if __name__ == "__main__":
    import json
    summary = get_dashboard_summary()
    print(json.dumps(summary, indent=2))
