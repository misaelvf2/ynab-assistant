---
name: ynab-api
description: >
  Interact with the YNAB (You Need A Budget) API using the official Python SDK
  and a caching wrapper. Covers authentication, SDK methods, data formats,
  and milliunits currency. Use when building tools that read or write YNAB
  budget data. Budget-agnostic.
---

# YNAB API

This skill teaches how to interact with the YNAB REST API via the official `ynab` Python SDK (v4.0.0+) and a project-local caching wrapper.

## Authentication

The YNAB Personal Access Token is loaded from:
1. Environment variable `YNAB_PAT`, or
2. A `.env` file at the project root (gitignored)

The `YNABClient` wrapper handles token loading automatically. For direct SDK usage:

```python
import ynab
config = ynab.Configuration(access_token="your_token")
api_client = ynab.ApiClient(config)
```

## The YNABClient Wrapper

**Location:** `ynab_assistant/client.py`

A thin layer over the SDK that provides two things only:
1. **Transparent file-based caching** — so scripts don't hammer the API
2. **Dict conversion** — normalizes SDK quirks (`var_date`→`date`, enums→strings, date objects→strings) via `model_dump(mode='json', by_alias=True)`

It is **not** meant to mirror the SDK. For any SDK method, use `client.cached_call()` directly.

```python
from ynab_assistant import YNABClient
client = YNABClient(use_cache=True)  # cache enabled by default
```

The client reads `budget_id` from `config.json` at `config["ynab"]["budget_id"]`.
The raw SDK `ApiClient` is available at `client.api` for direct SDK usage.

### `cached_call()` — the core mechanism

Every read goes through this single method:

```python
client.cached_call(
    label,          # Cache key label (e.g. "get_accounts")
    sdk_callable,   # The SDK method to call
    *args, **kwargs,  # Passed through to the SDK method
    extract=...,    # Pull relevant data from response (e.g. lambda r: r.data.accounts)
    ttl=300,        # Cache TTL in seconds (default: 5 min)
)
```

Example — calling an SDK method not covered by convenience methods:

```python
api = ynab.PayeesApi(client.api)
payees = client.cached_call(
    "get_payees", api.get_payees, client.budget_id,
    extract=lambda r: r.data.payees,
)
```

### Convenience Methods

Common operations that encode small details (budget_id injection, date string→object conversion, SDK method name quirks like `get_plan_month`):

| Method | Returns | Description |
|--------|---------|-------------|
| `get_accounts()` | `list[dict]` | All accounts |
| `get_categories()` | `list[dict]` | Category groups with nested categories |
| `get_transactions(since_date=None)` | `list[dict]` | Transactions, optionally filtered by ISO date string |
| `get_month(month)` | `dict` | Budget month data. `month` format: `YYYY-MM-01` |
| `get_category_by_month(category_id, month)` | `dict` | Single category for a given month |
| `get_account_transactions(account_id)` | `list[dict]` | All transactions for one account (24hr cache) |
| `get_all_transactions()` | `list[dict]` | All transactions across accounts (24hr cache) |
| `update_transaction(txn_id, ...)` | `dict` | Update approved/memo/category_id/flag_color |
| `clear_cache()` | — | Delete all cached API responses |

## Data Formats

### Milliunits

All currency values in YNAB are integers in "milliunits" (dollars x 1000):
- `$19.99` = `19990` milliunits
- Negative values = outflows (spending)
- Positive values = inflows (income)

### Dates

- Transactions: `YYYY-MM-DD` (ISO format string)
- Month endpoints: `YYYY-MM-01` (always first of month)

### Account Types

`checking`, `savings`, `cash`, `creditCard`, `lineOfCredit`, `otherAsset`, `otherLiability`, `mortgage`, `autoLoan`, `studentLoan`, `personalLoan`, `medicalDebt`, `otherDebt`

- `on_budget: true` = liquid/operational accounts (checking, savings, credit cards)
- `on_budget: false` = tracking accounts (investments, property, loans)

### Category Structure

Categories are nested under category groups:
- `category_group_name` — the group (e.g., "Monthly Bills")
- `name` — the category (e.g., "Rent")
- `budgeted` — amount assigned this month (milliunits)
- `activity` — spending this month (negative milliunits)
- `balance` — remaining (milliunits)

### Transaction Fields

Key fields: `id`, `date`, `amount`, `payee_name`, `category_name`, `category_id`, `account_name`, `account_id`, `memo`, `approved`, `deleted`, `transfer_account_id`, `import_payee_name`, `cleared`, `flag_color`

## Caching

All reads through `cached_call()` are cached as JSON in `cache/api/`:
- **Default TTL:** 5 minutes (`CACHE_TTL_DEFAULT`)
- **Historical TTL:** 24 hours (`CACHE_TTL_HISTORICAL`) — pass `ttl=CACHE_TTL_HISTORICAL` for historical data
- Cache key: MD5 hash of label + arguments
- Caching is transparent — `cached_call()` handles it automatically
- Call `client.clear_cache()` to wipe all cached responses

## Utility Functions

Available as module-level imports from `ynab_assistant`:

| Function | Description |
|----------|-------------|
| `milliunits_to_dollars(mu)` | Convert milliunits to float dollars |
| `dollars_to_milliunits(d)` | Convert float dollars to milliunits int |
| `format_currency(mu)` | Format milliunits as `$X,XXX.XX` string |
| `get_month_string(year, month)` | Returns `YYYY-MM-01` format |
| `get_month_start_date(year, month)` | Returns `YYYY-MM-01` format |

Run scripts with: `uv run python scripts/<script>.py`

## Common Patterns

**Filtering transactions:**
```python
real_txns = [t for t in txns if not t['deleted'] and t['transfer_account_id'] is None]
```

**Computing spending from category data:**
```python
spent = -category["activity"]  # activity is negative for outflows
remaining = category["balance"]
```

**Iterating months:**
```python
from dateutil.relativedelta import relativedelta
current = date(2026, 3, 1)
previous = current - relativedelta(months=1)
```

## Direct SDK Usage

For operations not covered by the convenience methods, use the SDK directly through `client.api` (the raw `ynab.ApiClient`) and `client.cached_call()`. See `sdk-reference.md` in this skill directory for the full SDK API surface.

SDK repo: https://github.com/ynab/ynab-sdk-python
