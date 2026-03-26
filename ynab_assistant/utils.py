"""
Shared constants and utility functions for the YNAB assistant.
"""
import os
import json
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
ENV_FILE = PROJECT_ROOT / ".env"
CONFIG_FILE = PROJECT_ROOT / "config.json"
CACHE_DIR = PROJECT_ROOT / "cache"
REPORTS_DIR = PROJECT_ROOT / "reports"
API_CACHE_DIR = CACHE_DIR / "api"


def load_token() -> str:
    """Load YNAB PAT from environment or .env file

    Loads from .env file if it exists, but will also use environment variables
    if already set (e.g., in Docker, CI/CD, or shell). Environment variables
    take precedence over .env file values.
    """
    load_dotenv(ENV_FILE)

    token = os.getenv("YNAB_PAT")
    if not token:
        raise ValueError(
            "YNAB_PAT not found in environment or .env file. "
            f"Either set the YNAB_PAT environment variable or create {ENV_FILE} with YNAB_PAT=your_token"
        )

    return token


def load_config() -> dict:
    """Load config.json"""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"No config.json found at {CONFIG_FILE}")

    with open(CONFIG_FILE) as f:
        return json.load(f)


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
