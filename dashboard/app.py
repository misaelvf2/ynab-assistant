#!/usr/bin/env python3
"""
YNAB Dashboard - FastAPI web application
"""
import sys
from pathlib import Path

# Add scripts directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from data_service import (
    get_dashboard_summary,
    get_net_worth_data,
    get_net_worth_history,
    get_eating_out_data,
    get_spending_velocity_data,
    get_transaction_issues
)
from ynab_assistant import YNABClient

app = FastAPI(title="YNAB Dashboard", version="1.0.0")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the dashboard HTML."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/summary")
async def api_summary():
    """Get all dashboard data in one call."""
    return get_dashboard_summary()


@app.get("/api/net-worth")
async def api_net_worth():
    """Get current net worth breakdown."""
    return get_net_worth_data()


@app.get("/api/net-worth/history")
async def api_net_worth_history(months: int = 12):
    """Get net worth history for charts."""
    return get_net_worth_history(months=months)


@app.get("/api/eating-out")
async def api_eating_out():
    """Get eating out tracker data."""
    return get_eating_out_data()


@app.get("/api/spending/velocity")
async def api_spending_velocity(threshold: float = 10.0):
    """Get spending velocity analysis."""
    return get_spending_velocity_data(threshold_pct=threshold)


@app.get("/api/transactions/issues")
async def api_transaction_issues(days: int = 30):
    """Get transactions needing attention."""
    return get_transaction_issues(days=days)


@app.post("/api/refresh")
async def api_refresh():
    """Clear cache and return fresh data."""
    client = YNABClient()
    client.clear_cache()
    return get_dashboard_summary()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
