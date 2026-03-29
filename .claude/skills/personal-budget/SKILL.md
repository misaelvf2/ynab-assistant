---
name: personal-budget
description: >
  Personal budget management for a YNAB budget. Ships as a template with
  generic scripts; user-specific scripts are generated during onboarding.
  Use when the user asks about spending, net worth, transactions, or
  financial health. Builds on the ynab-api skill.
---

# Personal Budget Assistant

This skill builds on the `ynab-api` skill (`.claude/skills/ynab-api/SKILL.md`) for API mechanics, authentication, and data formats.

---

## Part 1: Onboarding

### Detection

Check these conditions to determine onboarding state:

| Condition | State | Action |
|-----------|-------|--------|
| `config.json` has empty `budget_id` | Not connected | Start from step 1 |
| `config.json` has `budget_id` but empty `spending_caps` | Connected, not personalized | Start from step 2 |
| `config.json` has `budget_id` and `spending_caps` populated | Fully set up | Skip onboarding |

If `config.json` doesn't exist at all, copy `config.template.json` to `config.json` and start from step 1.

### Onboarding steps

**Step 1 — Budget connection:**
- Check `.env` for `YNAB_PAT`. If missing, ask the user to create a YNAB personal access token at https://app.ynab.com/settings/developer and add it.
- Use the SDK to list available budgets: `ynab.BudgetsApi(client.api).get_budgets()`
- Let the user pick which budget to use. Write `budget_id` and `budget_name` to `config.json`.

**Step 2 — Fetch the user's budget structure:**
- Fetch categories via `client.get_categories()` and accounts via `client.get_accounts()`.
- Show the user their category groups and categories so they can reference them in the next steps.

**Step 3 — Interview (ask these questions):**

| Question | What it configures |
|----------|--------------------|
| "Are there categories you want to track with hard spending caps?" | `config.json` → `spending_caps` (need category name, ID, and dollar limit) |
| "Do you pay credit cards in full each month, or carry balances?" | `tone-guide.md` → interpretation intent for credit cards |
| "What are your savings categories and goals?" | Confirm `config.json` → `interpretation.savings_keywords` match their actual fund names |
| "What net worth milestones are you targeting?" | `config.json` → `net_worth.milestones` |
| "How should I talk to you about your finances?" (blunt, encouraging, coach-like, curmudgeonly) | `tone-guide.md` → personality section |
| "What does a good month look like for you?" (what to grade on) | `config.json` → `grading` |

**Step 4 — Generate files:**
- Write user-specific fields to `config.json` (see Part 2 for schema)
- Write `tone-guide.md` (see `tone-guide.example.md` for format)
- Generate user-specific scripts in `user_scripts/` based on their spending caps and grading preferences (see Part 2 for patterns)
- Generate dashboard plugins in `dashboard/plugins/` for any tracked categories
- Fill in Part 3 of this SKILL.md with the user's script docs and routing table

---

## Part 2: Script Generation Guide

### Where scripts live

| Type | Directory | Criteria |
|------|-----------|----------|
| Generic | `scripts/` | Works for any YNAB budget. No user-specific categories, thresholds, or grading logic. |
| User-specific | `user_scripts/` | Tied to user's budget rules — tracked category caps, grading dimensions, approval preferences. |

### Patterns for user-specific scripts

**Category tracker** (e.g., eating out tracker):
- Reads category ID and spending cap from `config.json` → `spending_caps`
- Fetches category data via `client.get_category_by_month(category_id, month_str)`
- Calculates pace: daily average, projected total, daily runway
- Generates markdown report with executive summary, metrics table, pace table
- Optional `-t` flag to show individual transactions

**Monthly retrospective with grading**:
- Reads grading dimensions and thresholds from `config.json` → `grading`
- Scores across user-defined dimensions (budget adherence, category caps, savings, hygiene)
- Letter grade based on total score
- Prose analysis for each section (cash flow, spending, savings, net worth)
- References `tone-guide.md` for commentary tone

**Transaction approval**:
- Compares unapproved transactions against historical patterns
- Reads system category names from `config.json` → `interpretation.system_categories`
- Supports `--dry-run` before `--approve`

### Patterns for dashboard plugins

Plugins live in `dashboard/plugins/`. Each plugin is a `.py` file with a `register(app)` function:

```python
from fastapi import FastAPI

def register(app: FastAPI):
    @app.get("/api/my-widget")
    async def api_my_widget():
        return {"data": "..."}
```

- Data functions live in the plugin file itself (not in `data_service.py`)
- Read config via `load_config()`
- The app auto-discovers all plugins on startup

### User-specific keys in `config.json`

During onboarding, add these keys to `config.json` (see `config.template.json` for empty defaults):

```json
{
  "spending_caps": {
    "<category_slug>": {
      "monthly_limit": <dollars>,
      "category_name": "<YNAB category name>",
      "category_id": "<YNAB category UUID>"
    }
  },
  "net_worth": {
    "milestones": [<dollar amounts>],
    "debt_concern_threshold": <dollars>
  },
  "grading": {
    "dimensions": { "<name>": {"max_points": <n>, "weight": "<description>"} },
    "letter_grades": { "A": 90, "B": 80, "C": 70, "D": 60 }
  }
}
```

---

## Part 3: User Rules (filled in after onboarding)

<!-- This section is populated during onboarding. In the template, it's blank. -->

### Spending Rules

<!-- Populated during onboarding. Example entries:
1. **Eating out hard cap**: `config.json` → `spending_caps.<category>.monthly_limit`
2. **Large transaction flag**: `config.json` → `review_settings.flag_large_transactions_above`
3. **Memo requirement**: `config.json` → `review_settings.require_memo_for_transactions_above`
4. **Payee categorization rules**: e.g. "Cafeteria $10+ = lunch (Eating Out), <$5 = snack (Fun Money)"
5. **AI-Approved flag**: agent-approved transactions flagged orange in YNAB
-->

See `tone-guide.md` for personality, interpretation rules, and commentary guidance.

### User-Specific Scripts (`user_scripts/`)

<!-- Populated during onboarding. Document each generated script here with:
- Trigger phrases
- Usage / CLI flags
- What config it reads from
-->

### Request Routing

| User says | Run |
|-----------|-----|
| "Show me my spending this month" | `scripts/spending_summary.py` |
| "What's my net worth?" | `scripts/net_worth.py --save` |
| "How has my net worth grown?" | `scripts/net_worth_history.py` |
| "Review my transactions" | `scripts/review_transactions.py` |
| "How's my spending pace?" | `scripts/spending_velocity.py` |
| "Financial checkup" | Run all scripts and summarize |
| "Show me the dashboard" | `uv run uvicorn dashboard.app:app --reload --port 8000` |

<!-- Add user-specific script routes here during onboarding -->

---

## Generic Scripts (`scripts/`)

Run via `uv run python scripts/<script>.py`.

### spending_summary.py
**Triggers:** monthly spending, budget status, category breakdowns
```
uv run python scripts/spending_summary.py [-y YEAR] [-m MONTH]
```

### net_worth.py
**Triggers:** net worth, assets, liabilities, financial health
```
uv run python scripts/net_worth.py [--save] [--compare DATE] [--list-snapshots]
```
- `--save` — snapshot current net worth for future comparison
- `--compare DATE` — compare against a previous snapshot (YYYY-MM-DD)
- `--list-snapshots` — list available snapshots

### net_worth_history.py
**Triggers:** net worth growth, trends, historical analysis
```
uv run python scripts/net_worth_history.py [--months N]
```
- `--months N` — number of months to analyze (default: 24)

### review_transactions.py
**Triggers:** review transactions, check for issues, financial checkup
```
uv run python scripts/review_transactions.py [--days N] [--memo-threshold N]
```
- `--days N` — days to look back (default: 30)
- `--memo-threshold N` — flag missing memos above this dollar amount (default: 100)

### spending_velocity.py
**Triggers:** spending pace, budget runway, projections, running hot
```
uv run python scripts/spending_velocity.py [--threshold N] [--alerts-only]
```
- `--threshold N` — alert when category is N% ahead of pace (default: 10)
- `--alerts-only` — only show overspent and warning categories

## Reports

All scripts save markdown + HTML to `reports/`:

| Report | Filename Pattern |
|--------|-----------------|
| Eating Out | `YYYY-MM_eating-out.md` |
| Spending Summary | `YYYY-MM_spending.md` |
| Net Worth | `YYYY-MM-DD_net-worth.md` |
| Net Worth History | `YYYY-MM-DD_net-worth-history.md` |
| Transaction Review | `YYYY-MM-DD_transaction-review.md` |
| Transaction Approval | `YYYY-MM-DD_transaction-approval.md` |
| Monthly Retrospective | `YYYY-MM_monthly-retrospective.md` |

Reports are overwritten when regenerated for the same period. Read previous reports to compare or reference.

## Operational Rules

- **Config-driven values**: All settings live in `config.json` — generic (savings keywords, skip groups, review thresholds) and user-specific (spending caps, milestones, grading). Use `load_config()`.
- **Transaction filtering**: Always exclude `deleted` and `transfer_account_id is not None` (internal transfers).
- **Negative budgeted values** on categories = credit card payment tracking — skip in spending analyses.

## Dashboard

- **Data service**: `dashboard/data_service.py` provides structured dict data for programmatic access
- **Web app**: `dashboard/app.py` (FastAPI) at port 8000
- **Start**: `uv run uvicorn dashboard.app:app --reload --port 8000`
- **Plugins**: `dashboard/plugins/` — user-specific widgets auto-loaded on startup via `register(app)`
- **Generic endpoints**: `/api/summary`, `/api/net-worth`, `/api/net-worth/history`, `/api/spending/velocity`, `/api/transactions/issues`, `/api/refresh`
- **Plugin endpoints**: added per-user during onboarding (e.g. `/api/eating-out`)

## Configuration

- `config.json` — all settings: budget connection, review thresholds, interpretation, spending caps, milestones, grading (generated during onboarding, gitignored). Template: `config.template.json`.
- `.env` (gitignored) — `YNAB_PAT` token
- `cache/` — net worth snapshots (`net_worth_snapshots.json`) and API response cache (`api/`)
- `reports/` — generated markdown and HTML reports

Use `load_config()` for all settings.

Personality, interpretation intent (credit cards, savings), and commentary guidance are in `tone-guide.md` — the single owner for all agent-behavior rules. See `tone-guide.example.md` for the template format.
