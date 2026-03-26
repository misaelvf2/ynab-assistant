"""
YNAB API Client — thin caching + dict-conversion layer over the official SDK.

This wrapper exists for two reasons only:
1. Transparent file-based caching (so scripts don't hammer the API)
2. Dict conversion (normalizes SDK quirks: var_date→date, enums→strings)

It is NOT meant to mirror the SDK's API surface. For operations not covered
by the convenience methods below, use client.api directly.
"""
import json
import hashlib
from datetime import datetime, date, timedelta
from typing import Optional

import ynab

from ynab_assistant.utils import load_token, load_config, CACHE_DIR, API_CACHE_DIR

# Cache TTL settings (in seconds)
CACHE_TTL_DEFAULT = 300  # 5 minutes for most data
CACHE_TTL_HISTORICAL = 86400  # 24 hours for historical/static data


def _model_to_dict(obj) -> dict | list | str | int | float | bool | None:
    """Convert a Pydantic model (or list of models) to a JSON-serializable dict.

    Uses by_alias=True so that SDK field aliases (e.g. var_date -> date)
    match the raw YNAB API JSON format that existing scripts expect.
    """
    if isinstance(obj, list):
        return [_model_to_dict(item) for item in obj]
    if hasattr(obj, 'model_dump'):
        return obj.model_dump(mode='json', by_alias=True)
    return obj


class YNABClient:
    def __init__(self, use_cache: bool = True):
        self.token = load_token()
        self.config = load_config()
        self.budget_id = self.config["ynab"]["budget_id"]
        self.use_cache = use_cache
        self.cache_stats = {"hits": 0, "misses": 0}

        # Set up SDK client
        configuration = ynab.Configuration(access_token=self.token)
        self.api = ynab.ApiClient(configuration)
        self._accounts_api = ynab.AccountsApi(self.api)
        self._categories_api = ynab.CategoriesApi(self.api)
        self._transactions_api = ynab.TransactionsApi(self.api)
        self._months_api = ynab.MonthsApi(self.api)

        # Ensure cache directories exist
        CACHE_DIR.mkdir(exist_ok=True)
        API_CACHE_DIR.mkdir(exist_ok=True)

    # -- Caching internals ---------------------------------------------------

    def _cache_key(self, label: str, *args, **kwargs) -> str:
        key_data = label + json.dumps(
            [str(a) for a in args] + [f"{k}={v}" for k, v in sorted(kwargs.items())],
            sort_keys=True
        )
        return hashlib.md5(key_data.encode()).hexdigest()

    def _get_cached(self, cache_key: str, ttl: int):
        if not self.use_cache:
            return None

        cache_file = API_CACHE_DIR / f"{cache_key}.json"
        if not cache_file.exists():
            return None

        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime > timedelta(seconds=ttl):
            return None

        try:
            with open(cache_file) as f:
                self.cache_stats["hits"] += 1
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return None

    def _set_cached(self, cache_key: str, data):
        if not self.use_cache:
            return
        cache_file = API_CACHE_DIR / f"{cache_key}.json"
        with open(cache_file, "w") as f:
            json.dump(data, f)

    # -- Core: cached SDK call ------------------------------------------------

    def cached_call(self, label, sdk_callable, *args,
                    extract=lambda r: r, ttl=CACHE_TTL_DEFAULT, **kwargs):
        """Call an SDK method with caching and dict conversion.

        Args:
            label: Cache key label (e.g. "get_accounts").
            sdk_callable: The SDK method to call.
            *args, **kwargs: Passed through to the SDK method.
            extract: Function to pull the relevant data from the SDK response
                     (e.g. lambda r: r.data.accounts). Defaults to identity.
            ttl: Cache TTL in seconds.

        Returns:
            The SDK response data as plain dicts/lists.
        """
        key = self._cache_key(label, *args, **kwargs)
        cached = self._get_cached(key, ttl)
        if cached is not None:
            return cached

        self.cache_stats["misses"] += 1
        response = sdk_callable(*args, **kwargs)
        result = _model_to_dict(extract(response))
        self._set_cached(key, result)
        return result

    def clear_cache(self):
        """Clear all cached API responses."""
        for cache_file in API_CACHE_DIR.glob("*.json"):
            cache_file.unlink()
        print("Cache cleared")

    # -- Convenience methods --------------------------------------------------
    # These exist because they're called everywhere and encode small details
    # (budget_id injection, date string→object conversion, SDK method name
    # mapping like get_plan_month). For anything else, use client.api directly
    # with client.cached_call().

    def get_accounts(self) -> list:
        return self.cached_call(
            "get_accounts", self._accounts_api.get_accounts, self.budget_id,
            extract=lambda r: r.data.accounts,
        )

    def get_categories(self) -> list:
        return self.cached_call(
            "get_categories", self._categories_api.get_categories, self.budget_id,
            extract=lambda r: r.data.category_groups,
        )

    def get_transactions(self, since_date: Optional[str] = None) -> list:
        kwargs = {}
        if since_date:
            kwargs["since_date"] = date.fromisoformat(since_date)
        return self.cached_call(
            "get_transactions", self._transactions_api.get_transactions,
            self.budget_id, **kwargs,
            extract=lambda r: r.data.transactions,
        )

    def get_month(self, month: str) -> dict:
        return self.cached_call(
            "get_month", self._months_api.get_plan_month,
            self.budget_id, date.fromisoformat(month),
            extract=lambda r: r.data.month,
        )

    def get_category_by_month(self, category_id: str, month: str) -> dict:
        return self.cached_call(
            "get_category_by_month", self._categories_api.get_month_category_by_id,
            self.budget_id, date.fromisoformat(month), category_id,
            extract=lambda r: r.data.category,
        )

    def get_account_transactions(self, account_id: str) -> list:
        return self.cached_call(
            "get_account_transactions", self._transactions_api.get_transactions_by_account,
            self.budget_id, account_id,
            extract=lambda r: r.data.transactions,
            ttl=CACHE_TTL_HISTORICAL,
        )

    def get_all_transactions(self) -> list:
        return self.cached_call(
            "get_all_transactions", self._transactions_api.get_transactions, self.budget_id,
            extract=lambda r: r.data.transactions,
            ttl=CACHE_TTL_HISTORICAL,
        )

    def update_transaction(self, transaction_id: str, approved: Optional[bool] = None,
                           memo: Optional[str] = None, category_id: Optional[str] = None,
                           flag_color: Optional[str] = None) -> dict:
        """Update a transaction. Not cached (write operation)."""
        fields = {}
        if approved is not None:
            fields["approved"] = approved
        if memo is not None:
            fields["memo"] = memo
        if category_id is not None:
            fields["category_id"] = category_id
        if flag_color is not None:
            fields["flag_color"] = flag_color

        wrapper = ynab.PutTransactionWrapper(
            transaction=ynab.ExistingTransaction(**fields)
        )
        response = self._transactions_api.update_transaction(
            self.budget_id, transaction_id, wrapper
        )
        return _model_to_dict(response.data.transaction)
