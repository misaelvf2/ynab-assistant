"""
YNAB API Client - Base module for interacting with YNAB API
"""
import os
import json
import hashlib
import requests
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

# Find project root (where .env lives)
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_FILE = PROJECT_ROOT / "config.json"
CACHE_DIR = PROJECT_ROOT / "cache"
REPORTS_DIR = PROJECT_ROOT / "reports"
API_CACHE_DIR = CACHE_DIR / "api"

BASE_URL = "https://api.ynab.com/v1"

# Cache TTL settings (in seconds)
CACHE_TTL_DEFAULT = 300  # 5 minutes for most data
CACHE_TTL_HISTORICAL = 86400  # 24 hours for historical/static data


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
    def __init__(self, use_cache: bool = True):
        self.token = load_token()
        self.config = load_config()
        self.budget_id = self.config["ynab"]["budget_id"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.use_cache = use_cache
        self.cache_stats = {"hits": 0, "misses": 0}

        # Ensure cache directories exist
        CACHE_DIR.mkdir(exist_ok=True)
        API_CACHE_DIR.mkdir(exist_ok=True)

    def _get_cache_key(self, endpoint: str, params: Optional[dict] = None) -> str:
        """Generate a cache key from endpoint and params"""
        key_data = endpoint + (json.dumps(params, sort_keys=True) if params else "")
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_cached(self, cache_key: str, ttl: int) -> Optional[dict]:
        """Get cached response if valid"""
        if not self.use_cache:
            return None

        cache_file = API_CACHE_DIR / f"{cache_key}.json"
        if not cache_file.exists():
            return None

        # Check if cache is expired
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime > timedelta(seconds=ttl):
            return None

        try:
            with open(cache_file) as f:
                self.cache_stats["hits"] += 1
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _set_cached(self, cache_key: str, data: dict):
        """Save response to cache"""
        if not self.use_cache:
            return

        cache_file = API_CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, "w") as f:
            json.dump(data, f)

    def _get(self, endpoint: str, params: Optional[dict] = None,
             ttl: int = CACHE_TTL_DEFAULT) -> dict:
        """Make GET request to YNAB API with caching"""
        cache_key = self._get_cache_key(endpoint, params)

        # Try cache first
        cached = self._get_cached(cache_key, ttl)
        if cached is not None:
            return cached

        # Make API request
        self.cache_stats["misses"] += 1
        url = f"{BASE_URL}{endpoint}"
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        data = response.json()["data"]

        # Cache the response
        self._set_cached(cache_key, data)

        return data

    def clear_cache(self):
        """Clear all cached API responses"""
        for cache_file in API_CACHE_DIR.glob("*.json"):
            cache_file.unlink()
        print(f"Cache cleared")

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

    def get_account_transactions(self, account_id: str) -> list:
        """Get all transactions for a specific account (cached longer for historical data)"""
        data = self._get(
            f"/budgets/{self.budget_id}/accounts/{account_id}/transactions",
            ttl=CACHE_TTL_HISTORICAL
        )
        return data["transactions"]

    def get_all_transactions(self) -> list:
        """Get all transactions (cached longer for historical data)"""
        data = self._get(
            f"/budgets/{self.budget_id}/transactions",
            ttl=CACHE_TTL_HISTORICAL
        )
        return data["transactions"]


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


def save_report(report_type: str, content: str, month_str: str = None) -> tuple[Path, Path]:
    """Save a report to the reports directory in both Markdown and HTML formats.

    Args:
        report_type: Type of report (e.g., 'eating-out', 'spending', 'net-worth')
        content: Markdown content of the report
        month_str: Optional month string (YYYY-MM) for the report filename

    Returns:
        Tuple of (markdown_path, html_path)
    """
    import markdown

    REPORTS_DIR.mkdir(exist_ok=True)

    today = date.today()
    if month_str:
        base_filename = f"{month_str}_{report_type}"
    else:
        base_filename = f"{today.isoformat()}_{report_type}"

    # Save markdown
    md_path = REPORTS_DIR / f"{base_filename}.md"
    with open(md_path, "w") as f:
        f.write(content)

    # Convert to HTML and save
    html_content = markdown.markdown(content, extensions=['tables', 'fenced_code'])
    html_full = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{report_type.replace('-', ' ').title()} Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; line-height: 1.6; }}
        h1 {{ color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        h3 {{ color: #7f8c8d; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #3498db; color: white; }}
        tr:nth-child(even) {{ background-color: #f9f9f9; }}
        tr:hover {{ background-color: #f5f5f5; }}
        .executive-summary {{ background: #f8f9fa; border-left: 4px solid #3498db; padding: 20px; margin: 20px 0; }}
        strong {{ color: #2c3e50; }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 30px 0; }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""

    html_path = REPORTS_DIR / f"{base_filename}.html"
    with open(html_path, "w") as f:
        f.write(html_full)

    return md_path, html_path


if __name__ == "__main__":
    # Quick test
    client = YNABClient()
    print(f"Connected to budget: {client.config['ynab']['budget_name']}")
    accounts = client.get_accounts()
    print(f"Found {len(accounts)} accounts")
