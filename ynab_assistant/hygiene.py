"""
Budget-hygiene helpers shared by the approval, categorization, and
assignment scripts. Read-only: nothing here writes to YNAB.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from dateutil.relativedelta import relativedelta

from ynab_assistant.utils import load_config


def is_real(txn: dict) -> bool:
    """Not deleted and not an internal transfer."""
    return not txn["deleted"] and txn["transfer_account_id"] is None


def is_split(txn: dict) -> bool:
    return bool(txn.get("subtransactions"))


def payee_key(txn: dict) -> str:
    """Normalized payee for pattern matching (display name first, import name as fallback)."""
    name = txn.get("payee_name") or txn.get("import_payee_name") or ""
    return " ".join(name.lower().split())


def import_key(txn: dict) -> str:
    return " ".join((txn.get("import_payee_name") or "").lower().split())


def history_since(months: int = 12) -> str:
    return (date.today().replace(day=1) - relativedelta(months=months)).isoformat()


def load_history(client, months: int = 12) -> list[dict]:
    """Approved, categorized, non-transfer transactions — the trusted pattern base."""
    txns = client.get_transactions(since_date=history_since(months))
    return [
        t for t in txns
        if is_real(t) and t["approved"] and t["category_id"] and not is_split(t)
    ]


class PayeeHistory:
    """Category distribution per payee, built from trusted history."""

    def __init__(self, history: list[dict]):
        self.by_payee: dict[str, Counter] = defaultdict(Counter)
        self.by_import: dict[str, Counter] = defaultdict(Counter)
        self.names: dict[str, str] = {}
        for t in history:
            key = payee_key(t)
            if key:
                self.by_payee[key][(t["category_id"], t["category_name"])] += 1
            ikey = import_key(t)
            if ikey:
                self.by_import[ikey][(t["category_id"], t["category_name"])] += 1
            if t["category_id"]:
                self.names[t["category_id"]] = t["category_name"]

    def distribution(self, txn: dict) -> Counter:
        dist = Counter(self.by_payee.get(payee_key(txn), Counter()))
        if not dist:
            dist = Counter(self.by_import.get(import_key(txn), Counter()))
        return dist

    def suggest(self, txn: dict) -> dict:
        """Return {category_id, category_name, confidence, samples, alternatives}."""
        dist = self.distribution(txn)
        total = sum(dist.values())
        if total == 0:
            return {"category_id": None, "category_name": None, "confidence": 0.0,
                    "samples": 0, "alternatives": []}
        ranked = dist.most_common()
        (cat_id, cat_name), count = ranked[0]
        return {
            "category_id": cat_id,
            "category_name": cat_name,
            "confidence": round(count / total, 3),
            "samples": total,
            "alternatives": [
                {"category_name": n, "category_id": i, "count": c}
                for (i, n), c in ranked[1:4]
            ],
        }

    def supports(self, txn: dict) -> int:
        """How many trusted transactions share this payee *and* category."""
        dist = self.distribution(txn)
        return dist.get((txn["category_id"], txn["category_name"]), 0)


def on_budget_account_ids(client) -> set[str]:
    """Ids of on-budget accounts. Tracking-account transactions carry no category."""
    return {a["id"] for a in client.get_accounts() if a["on_budget"] and not a["deleted"]}


def needs_category(txn: dict, on_budget: set[str]) -> bool:
    """Uncategorized *and* on an on-budget account (tracking accounts never have one)."""
    return is_real(txn) and txn["category_id"] is None and txn["account_id"] in on_budget


def inflow_category_name() -> str:
    cfg = load_config()
    return cfg.get("interpretation", {}).get("system_categories", {}).get("inflow", "Inflow: Ready to Assign")


def find_duplicate_ids(txns: list[dict]) -> set[str]:
    """Ids of transactions sharing account, date, and amount with another transaction."""
    groups = defaultdict(list)
    for t in txns:
        if t["deleted"]:
            continue
        groups[(t["account_id"], t["date"], t["amount"])].append(t["id"])
    return {tid for ids in groups.values() if len(ids) > 1 for tid in ids}


def large_threshold_mu() -> int:
    cfg = load_config()
    dollars = cfg.get("review_settings", {}).get("flag_large_transactions_above", 500)
    return int(dollars * 1000)


def txn_context(txn: dict) -> dict:
    return {
        "date": txn["date"],
        "payee": txn.get("payee_name"),
        "amount": txn["amount"],
        "account": txn.get("account_name"),
        "category_name": txn.get("category_name"),
    }


def month_range(months: int, end: date | None = None) -> list[str]:
    """Last ``months`` month strings (YYYY-MM-01), oldest first, ending with ``end``'s month."""
    end = (end or date.today()).replace(day=1)
    return [(end - relativedelta(months=i)).isoformat() for i in range(months - 1, -1, -1)]
