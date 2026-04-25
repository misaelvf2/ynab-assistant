"""
Eating Out Dashboard Widget — user-specific plugin.

Adds /api/eating-out endpoint that tracks spending against
the user's eating out hard cap from config.json.
"""
from calendar import monthrange
from datetime import date

from fastapi import FastAPI

from ynab_assistant import YNABClient, load_config, milliunits_to_dollars

WIDGET_META = {
    "id": "eating-out",
    "title": "Eating Out",
    "endpoint": "/api/eating-out",
    "widget_type": "spending-cap",
}


def get_eating_out_data(year: int = None, month: int = None) -> dict:
    """Get eating out tracker data."""
    client = YNABClient()
    user_config = load_config()
    today = date.today()

    if year is None:
        year = today.year
    if month is None:
        month = today.month

    eating_out_config = user_config.get("spending_caps", {}).get("eating_out", {})
    if not eating_out_config:
        return {"error": "No eating_out spending cap configured in config.json"}

    hard_cap = eating_out_config["monthly_limit"]
    category_id = eating_out_config["category_id"]

    month_str = f"{year}-{month:02d}-01"
    category_data = client.get_category_by_month(category_id, month_str)

    activity = abs(category_data.get("activity", 0))
    budgeted = category_data.get("budgeted", 0)

    spent = milliunits_to_dollars(activity)
    remaining = hard_cap - spent

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

    if spent > hard_cap:
        status = "over"
    elif projected > hard_cap:
        status = "warning"
    elif spent > hard_cap * 0.8:
        status = "caution"
    else:
        status = "on_track"

    return {
        "title": WIDGET_META["title"],
        "widget_type": WIDGET_META["widget_type"],
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
        "percent_month": (days_elapsed / days_in_month * 100),
    }


def register(app: FastAPI):
    """Register eating out widget routes."""

    @app.get("/api/eating-out")
    async def api_eating_out():
        """Get eating out tracker data."""
        return get_eating_out_data()
