"""
YNAB API Client - Base module for interacting with YNAB API
"""
import os
import json
import requests
from datetime import datetime, date
from pathlib import Path
from typing import Optional

# Find project root (where .env lives)
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_FILE = PROJECT_ROOT / "config.json"
CACHE_DIR = PROJECT_ROOT / "cache"
REPORTS_DIR = PROJECT_ROOT / "reports"

BASE_URL = "https://api.ynab.com/v1"


def load_token() -> str:
    """Load YNAB PAT from .env file"""
    if not ENV_FILE.exists():
        raise FileNotFoundError(f"No .env file found at {ENV_FILE}")

    with open(ENV_FILE) as f:
        for line in f:
            if line.startswith("YNAB_PAT="):
                return line.strip().split("=", 1)[1]

    raise ValueError("YNAB_PAT not found in .env file")


def load_config() -> dict:
    """Load config.json"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"No config.json found at {CONFIG_FILE}")

    with open(CONFIG_FILE) as f:
        return json.load(f)


class YNABClient:
    def __init__(self):
        self.token = load_token()
        self.config = load_config()
        self.budget_id = self.config["ynab"]["budget_id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

        # Ensure cache directory exists
        CACHE_DIR.mkdir(exist_ok=True)

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make GET request to YNAB API"""
        url = f"{BASE_URL}{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()["data"]

    def get_accounts(self) -> list:
        """Get all accounts"""
        data = self._get(f"/budgets/{self.budget_id}/accounts")
        return data["accounts"]

    def get_categories(self) -> list:
        """Get all category groups with categories"""
        data = self._get(f"/budgets/{self.budget_id}/categories")
        return data["category_groups"]

    def get_transactions(self, since_date: Optional[str] = None) -> list:
        """Get transactions, optionally filtered by date"""
        params = {}
        if since_date:
            params["since_date"] = since_date
        data = self._get(f"/budgets/{self.budget_id}/transactions", params)
        return data["transactions"]

    def get_month(self, month: str) -> dict:
        """Get budget month data (format: YYYY-MM-01)"""
        data = self._get(f"/budgets/{self.budget_id}/months/{month}")
        return data["month"]

    def get_category_by_month(self, category_id: str, month: str) -> dict:
        """Get specific category data for a month"""
        data = self._get(f"/budgets/{self.budget_id}/months/{month}/categories/{category_id}")
        return data["category"]


def milliunits_to_dollars(milliunits: int) -> float:
    """Convert YNAB milliunits to dollars"""
    return milliunits / 1000


def dollars_to_milliunits(dollars: float) -> int:
    """Convert dollars to YNAB milliunits"""
    return int(dollars * 1000)


def format_currency(milliunits: int) -> str:
    """Format milliunits as currency string"""
    dollars = milliunits_to_dollars(milliunits)
    return f"${dollars:,.2f}"


def get_month_string(year: int = None, month: int = None) -> str:
    """Get YNAB-formatted month string (YYYY-MM-01)"""
    if year is None or month is None:
        today = date.today()
        year = today.year
        month = today.month
    return f"{year:04d}-{month:02d}-01"


def get_month_start_date(year: int = None, month: int = None) -> str:
    """Get first day of month as YYYY-MM-DD"""
    if year is None or month is None:
        today = date.today()
        year = today.year
        month = today.month
    return f"{year:04d}-{month:02d}-01"


def save_report(report_type: str, content: str, month_str: str = None) -> Path:
    """Save a report to the reports directory.

    Args:
        report_type: Type of report (e.g., 'eating-out', 'spending', 'net-worth')
        content: Markdown content of the report
        month_str: Optional month string (YYYY-MM) for the report filename

    Returns:
        Path to the saved report
    """
    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today()
    if month_str:
        filename = f"{month_str}_{report_type}.md"
    else:
        filename = f"{today.isoformat()}_{report_type}.md"

    filepath = REPORTS_DIR / filename
    with open(filepath, "w") as f:
        f.write(content)

    return filepath


if __name__ == "__main__":
    # Quick test
    client = YNABClient()
    print(f"Connected to budget: {client.config['ynab']['budget_name']}")
    accounts = client.get_accounts()
    print(f"Found {len(accounts)} accounts")
