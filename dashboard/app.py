#!/usr/bin/env python3
"""
YNAB Dashboard - FastAPI web application

Generic endpoints ship with the tool. User-specific widgets live in
dashboard/plugins/ — each plugin is a Python module with a register(app)
function that adds its own routes.
"""
import importlib
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .data_service import (
    get_dashboard_summary,
    get_net_worth_data,
    get_net_worth_history,
    get_spending_velocity_data,
    get_transaction_issues
)
from ynab_assistant import YNABClient

app = FastAPI(title="YNAB Dashboard", version="1.0.0")

# Templates
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


# -- Plugin loading -----------------------------------------------------------

PLUGINS_DIR = Path(__file__).parent / "plugins"


def load_plugins(application: FastAPI):
    """Discover and register plugins from the plugins/ directory.

    Each plugin is a .py file (not starting with _) that exposes a
    register(app) function. The function receives the FastAPI app and
    can add routes, middleware, or startup hooks.
    """
    if not PLUGINS_DIR.is_dir():
        return

    for plugin_path in sorted(PLUGINS_DIR.glob("*.py")):
        if plugin_path.name.startswith("_"):
            continue
        module_name = f"dashboard.plugins.{plugin_path.stem}"
        try:
            module = importlib.import_module(module_name)
            if hasattr(module, "register"):
                module.register(application)
        except Exception as exc:
            print(f"Warning: failed to load plugin {plugin_path.name}: {exc}")


load_plugins(app)


# -- Generic endpoints --------------------------------------------------------

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
