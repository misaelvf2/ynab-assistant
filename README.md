# YNAB Financial Assistant

A personal finance assistant that connects to [YNAB](https://www.ynab.com/) (You Need A Budget) to provide spending analysis, net worth tracking, and financial health diagnostics.

## Features

- **Spending Tracking**: Monthly spending by category with budget comparisons
- **Eating Out Monitor**: Hard cap tracking with daily runway and projections
- **Net Worth Analysis**: Current snapshot with asset/liability breakdown
- **Net Worth History**: Historical reconstruction with growth trends and charts
- **Transaction Review**: Flags uncategorized transactions, missing memos, and inconsistencies

## Setup

1. Clone the repo
2. Install [uv](https://docs.astral.sh/uv/) if you don't have it:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Install dependencies:
   ```bash
   uv sync
   ```
4. Set your YNAB Personal Access Token either:
   - Via environment variable: `export YNAB_PAT=your_token_here`
   - Or create a `.env` file:
     ```
     YNAB_PAT=your_token_here
     ```
5. Update `config.json` with your budget ID (run any script to see available budgets)

## Scripts

All scripts are in the `scripts/` directory. Run via `uv run python scripts/<script>.py`.

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `eating_out_tracker.py` | Track eating out against $600/mo cap | `-t` show transactions |
| `spending_summary.py` | Monthly spending by category | `--month YYYY-MM` |
| `net_worth.py` | Current net worth snapshot | `--save` to snapshot, `--compare DATE` |
| `net_worth_history.py` | Historical net worth trends | `--months N` (default 12) |
| `review_transactions.py` | Flag transaction issues | `--days N`, `--memo-threshold N` |
| `approve_transactions.py` | Review & approve transactions | `--approve` auto-approve, `--dry-run` preview |
| `spending_velocity.py` | Spending pace & projections | `--threshold N`, `--alerts-only` |

## Web Dashboard

A real-time dashboard showing all key metrics at a glance.

```bash
# Start the dashboard
uv run uvicorn dashboard.app:app --reload --port 8000

# Open http://localhost:8000
```

**Features:**
- Net worth with month-over-month change
- Eating out tracker with progress bar and daily allowance
- Spending velocity alerts (overspent, running hot)
- Transaction issues summary
- 12-month net worth trend chart
- On-demand refresh button

## Reports

Scripts generate reports in both Markdown and HTML formats, saved to `reports/`:

- Markdown for easy reading and diffing
- HTML with styled tables and (for net worth history) interactive Chart.js graphs

## Configuration

- `.env` - YNAB API token (gitignored)
- `config.json` - Budget IDs, spending caps, review thresholds
- `CLAUDE.md` - Instructions for Claude Code assistant sessions

## Caching

API responses are cached in `cache/api/` to reduce API calls:
- Default TTL: 5 minutes
- Historical data: 24 hours

Net worth snapshots are stored in `cache/net_worth_snapshots.json` for comparison over time.

## License

Personal use.
