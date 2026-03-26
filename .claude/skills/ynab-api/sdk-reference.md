# YNAB SDK Reference

Official Python SDK: `ynab` (v4.0.0+). Generated from the YNAB OpenAPI spec.

## Table of Contents

- [Initialization](#initialization)
- [API Classes](#api-classes)
- [Response Structure](#response-structure)
- [Write Operations](#write-operations)
- [Models](#models)
- [Error Handling](#error-handling)

## Initialization

```python
import ynab

config = ynab.Configuration(access_token="your_token")
with ynab.ApiClient(config) as api_client:
    accounts_api = ynab.AccountsApi(api_client)
    categories_api = ynab.CategoriesApi(api_client)
    transactions_api = ynab.TransactionsApi(api_client)
    months_api = ynab.MonthsApi(api_client)
    plans_api = ynab.PlansApi(api_client)
```

Note: The SDK uses "plans" instead of "budgets" in v4.0.0+. The first parameter to most methods is `plan_id` (the budget ID).

## API Classes

### AccountsApi

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_accounts(plan_id)` | `last_knowledge_of_server=` | `.data.accounts: list[Account]` |
| `get_account_by_id(plan_id, account_id)` | | `.data.account: Account` |
| `create_account(plan_id, data)` | `PostAccountWrapper` | `.data.account: Account` |

### TransactionsApi

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_transactions(plan_id)` | `since_date=`, `type=`, `last_knowledge_of_server=` | `.data.transactions: list[TransactionDetail]` |
| `get_transactions_by_account(plan_id, account_id)` | `since_date=`, `type=`, `last_knowledge_of_server=` | `.data.transactions: list[TransactionDetail]` |
| `get_transactions_by_category(plan_id, category_id)` | `since_date=`, `type=`, `last_knowledge_of_server=` | `.data.transactions: list[HybridTransaction]` |
| `get_transactions_by_month(plan_id, month)` | `since_date=`, `type=`, `last_knowledge_of_server=` | `.data.transactions: list[HybridTransaction]` |
| `get_transactions_by_payee(plan_id, payee_id)` | `since_date=`, `type=`, `last_knowledge_of_server=` | `.data.transactions: list[HybridTransaction]` |
| `get_transaction_by_id(plan_id, transaction_id)` | | `.data.transaction: TransactionDetail` |
| `create_transaction(plan_id, data)` | `PostTransactionsWrapper` | `.data.transactions: list` |
| `update_transaction(plan_id, transaction_id, data)` | `PutTransactionWrapper` | `.data.transaction: TransactionDetail` |
| `update_transactions(plan_id, data)` | `PatchTransactionsWrapper` | `.data.transactions: list` |
| `delete_transaction(plan_id, transaction_id)` | | `.data.transaction: TransactionDetail` |
| `import_transactions(plan_id)` | | `.data.transaction_ids: list` |

### CategoriesApi

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_categories(plan_id)` | `last_knowledge_of_server=` | `.data.category_groups: list[CategoryGroupWithCategories]` |
| `get_category_by_id(plan_id, category_id)` | | `.data.category: Category` |
| `get_month_category_by_id(plan_id, month, category_id)` | | `.data.category: Category` |
| `update_month_category(plan_id, month, category_id, data)` | `PatchMonthCategoryWrapper` | `.data.category: Category` |

### MonthsApi

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_plan_months(plan_id)` | `last_knowledge_of_server=` | `.data.months: list[MonthSummary]` |
| `get_plan_month(plan_id, month)` | | `.data.month: MonthDetail` |

### PlansApi

| Method | Parameters | Returns |
|--------|-----------|---------|
| `get_plans()` | `include_accounts=` | `.data.plans: list[PlanSummary]` |
| `get_plan_by_id(plan_id)` | | `.data.plan: PlanDetail` |

### Other APIs

- **PayeesApi**: `get_payees`, `get_payee_by_id`, `update_payee`
- **ScheduledTransactionsApi**: `get_scheduled_transactions`, `get_scheduled_transaction_by_id`, `create_scheduled_transaction`, `update_scheduled_transaction`, `delete_scheduled_transaction`
- **UserApi**: `get_user`
- **MoneyMovementsApi**: `get_money_movements`, `get_money_movement_groups`

## Response Structure

All SDK methods return typed response objects. Access data via `.data`:

```python
response = accounts_api.get_accounts(plan_id)
accounts = response.data.accounts  # list[Account]

for account in accounts:
    print(account.name, account.balance, account.type)
```

### Converting to Dicts

Use `model_dump(mode='json', by_alias=True)` to get JSON-compatible dicts:

```python
account_dict = account.model_dump(mode='json', by_alias=True)
# Returns: {'id': '...', 'name': 'Checking', 'type': 'checking', ...}
```

`by_alias=True` is important — it maps `var_date` back to `date` in transaction models.

## Write Operations

### Update a Transaction

```python
wrapper = ynab.PutTransactionWrapper(
    transaction=ynab.ExistingTransaction(approved=True)
)
response = transactions_api.update_transaction(plan_id, transaction_id, wrapper)
```

`ExistingTransaction` fields (all optional): `account_id`, `var_date`, `amount`, `payee_id`, `payee_name`, `category_id`, `memo`, `cleared`, `approved`, `flag_color`, `subtransactions`

### Create Transactions

```python
wrapper = ynab.PostTransactionsWrapper(
    transaction=ynab.NewTransaction(
        account_id="...",
        var_date=date(2026, 3, 25),
        amount=-19990,
        payee_name="Restaurant",
        category_id="...",
        memo="Dinner",
    )
)
response = transactions_api.create_transaction(plan_id, wrapper)
```

### Batch Update

```python
wrapper = ynab.PatchTransactionsWrapper(
    transactions=[
        ynab.SaveTransactionWithIdOrImportId(id="txn1", approved=True),
        ynab.SaveTransactionWithIdOrImportId(id="txn2", approved=True),
    ]
)
response = transactions_api.update_transactions(plan_id, wrapper)
```

## Models

### Key Model Fields

**Account**: `id`, `name`, `type` (AccountType enum), `on_budget`, `closed`, `balance`, `cleared_balance`, `uncleared_balance`, `deleted`

**TransactionDetail**: `id`, `date` (aliased from `var_date`), `amount`, `memo`, `cleared`, `approved`, `flag_color`, `account_id`, `account_name`, `payee_id`, `payee_name`, `category_id`, `category_name`, `transfer_account_id`, `import_payee_name`, `deleted`, `subtransactions`

**Category**: `id`, `category_group_id`, `category_group_name`, `name`, `hidden`, `budgeted`, `activity`, `balance`, `goal_type`, `goal_target`, `goal_target_month`, `goal_percentage_complete`, `deleted`

**MonthDetail**: `month`, `income`, `budgeted`, `activity`, `to_be_budgeted`, `age_of_money`, `categories`, `deleted`

### Enums

- **AccountType**: `checking`, `savings`, `cash`, `creditCard`, `lineOfCredit`, `otherAsset`, `otherLiability`, `mortgage`, `autoLoan`, `studentLoan`, `personalLoan`, `medicalDebt`, `otherDebt`
- **TransactionClearedStatus**: `cleared`, `uncleared`, `reconciled`
- **TransactionFlagColor**: `red`, `orange`, `yellow`, `green`, `blue`, `purple`

## Error Handling

```python
from ynab import ApiException

try:
    response = transactions_api.get_transactions(plan_id)
except ApiException as e:
    print(f"Status {e.status}: {e.reason}")
    # e.body contains the error response JSON
```

Common errors:
- **401**: Invalid or expired access token
- **404**: Budget/transaction/category not found
- **429**: Rate limited (200 requests per hour per access token)

## Delta Requests

Most GET methods accept `last_knowledge_of_server` for incremental fetching:

```python
response = transactions_api.get_transactions(plan_id, last_knowledge_of_server=1234)
new_knowledge = response.data.server_knowledge
# Only returns entities changed since server_knowledge 1234
```

Store and reuse `server_knowledge` to avoid re-fetching unchanged data.
