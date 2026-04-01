# YNAB Financial Assistant

A personal finance assistant powered by [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that connects to [YNAB](https://www.ynab.com/) (You Need A Budget). Instead of running scripts manually, you talk to Claude — ask about your spending, net worth, or transactions, and it runs the right tools, interprets the data, and responds in your preferred tone.

The project is built on Claude Code's [agent skills](https://docs.anthropic.com/en/docs/claude-code/skills) system. Two skill specs drive all behavior:

- `.claude/skills/ynab-api/SKILL.md` — YNAB SDK wrapper, caching, data formats
- `.claude/skills/personal-budget/SKILL.md` — Onboarding, script generation, budget rules, request routing

## How It Works

1. **You talk to Claude** — "What's my net worth?", "How's my spending pace?", "Review my transactions"
2. **Claude routes to the right script**, runs it, and reads the output
3. **Claude interprets the results** using your personalized tone and budget rules, then responds with commentary

Scripts produce structured data. Claude adds the personality and context. This separation keeps scripts reusable and lets the agent adapt its voice per user.

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
4. Add your YNAB Personal Access Token to a `.env` file:
   ```
   YNAB_PAT=your_token_here
   ```
   Get a token at https://app.ynab.com/settings/developer.

5. **Start a Claude Code session and let it onboard you.** Claude will:
   - Connect to your YNAB budget
   - Show your category structure
   - Ask about spending caps, savings goals, net worth milestones, and preferred tone
   - Generate `config.json`, `tone-guide.md`, user-specific scripts, and dashboard plugins

See the [personal-budget skill spec](.claude/skills/personal-budget/SKILL.md) for full onboarding details.

## Running Scripts Yourself

Once onboarded, you're free to run any script directly from the command line.

**Generic scripts** (work for any YNAB budget):

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `scripts/spending_summary.py` | Monthly spending by category | `-y YEAR`, `-m MONTH` |
| `scripts/net_worth.py` | Current net worth snapshot | `--save`, `--compare DATE`, `--list-snapshots` |
| `scripts/net_worth_history.py` | Historical net worth trends | `--months N` |
| `scripts/review_transactions.py` | Flag transaction issues | `--days N`, `--memo-threshold N` |
| `scripts/spending_velocity.py` | Spending pace & projections | `--threshold N`, `--alerts-only` |

```bash
uv run python scripts/spending_summary.py
uv run python scripts/net_worth.py --save
```

**User-specific scripts** are generated during onboarding into `user_scripts/` — these are tailored to your budget (e.g., category trackers with your spending caps, monthly retrospectives with your grading dimensions). See the personal-budget skill spec for the patterns used to generate them.

## Web Dashboard

```bash
uv run uvicorn dashboard.app:app --reload --port 8000
# Open http://localhost:8000
```

The dashboard serves generic endpoints (`/api/summary`, `/api/net-worth`, etc.) plus user-specific plugin endpoints generated during onboarding. Plugins live in `dashboard/plugins/` and are auto-discovered on startup.

## Reports

Scripts save Markdown and HTML reports to `reports/`, overwritten when regenerated for the same period. HTML reports include styled tables and interactive Chart.js graphs where applicable.

## Configuration

- `config.json` — All settings: budget connection, spending caps, milestones, grading, review thresholds (generated during onboarding from `config.template.json`, gitignored)
- `tone-guide.md` — Personality, interpretation rules, commentary guidance (generated during onboarding from `tone-guide.example.md`, gitignored)
- `.env` — YNAB API token (gitignored)

## Caching

API responses are cached in `cache/api/` (default 5-minute TTL, 24 hours for historical data). Net worth snapshots are stored in `cache/net_worth_snapshots.json`.

## License

[MIT](LICENSE)
