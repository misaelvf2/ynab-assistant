"""
Change journal — reversible, verifiable writes to YNAB.

Every effectful operation in this project follows the same three-step shape:

1. **plan**  — a read-only pass that decides what *would* change and saves it
               as JSON under ``changes/plans/`` for review (and hand-editing).
2. **apply** — executes a plan. Before each write the live state is compared
               against the plan's recorded ``before`` state; stale entries are
               skipped. Every write is verified against the API response and
               recorded (before + after) in a journal under ``changes/journals/``.
3. **undo**  — replays a journal in reverse, restoring the recorded ``before``
               state. Undo is itself journaled, so it can be undone too.

Two change types are supported:

- ``transaction``    — ``approved``, ``category_id``, ``memo``, ``flag_color``
- ``month_category`` — ``budgeted`` for one category in one month

Journals and plans contain transaction data, so ``changes/`` is gitignored.
"""

from __future__ import annotations

import json
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import ynab

from ynab_assistant.utils import PROJECT_ROOT

CHANGES_DIR = PROJECT_ROOT / "changes"
PLANS_DIR = CHANGES_DIR / "plans"
JOURNALS_DIR = CHANGES_DIR / "journals"

TRANSACTION_FIELDS = ("approved", "category_id", "memo", "flag_color")
DEFAULT_BATCH_SIZE = 50


# -- Plans ---------------------------------------------------------------------

def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H-%M-%S")


def save_plan(label: str, plan: dict) -> Path:
    """Persist a plan dict as JSON and return its path."""
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    plan.setdefault("label", label)
    plan.setdefault("created", datetime.now().isoformat(timespec="seconds"))
    path = PLANS_DIR / f"{_timestamp()}_{label}.json"
    with open(path, "w") as f:
        json.dump(plan, f, indent=2)
    return path


def load_plan(path: str | Path) -> dict:
    with open(path) as f:
        return json.load(f)


# -- Journals ------------------------------------------------------------------

class ChangeJournal:
    """Append-only record of applied changes, flushed to disk after every batch."""

    def __init__(self, label: str, budget_id: str, plan_file: Optional[str] = None,
                 undo_of: Optional[str] = None):
        JOURNALS_DIR.mkdir(parents=True, exist_ok=True)
        self.path = JOURNALS_DIR / f"{_timestamp()}_{label}.json"
        self.data = {
            "label": label,
            "budget_id": budget_id,
            "created": datetime.now().isoformat(timespec="seconds"),
            "plan_file": str(plan_file) if plan_file else None,
            "undo_of": str(undo_of) if undo_of else None,
            "entries": [],
            "skipped": [],
        }

    def record(self, entry: dict):
        entry["applied_at"] = datetime.now().isoformat(timespec="seconds")
        self.data["entries"].append(entry)

    def skip(self, entry: dict, reason: str):
        self.data["skipped"].append({**entry, "reason": reason})

    def flush(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    @property
    def entries(self) -> list:
        return self.data["entries"]


def load_journal(path: str | Path) -> dict:
    with open(path) as f:
        return json.load(f)


def list_journals() -> list[Path]:
    if not JOURNALS_DIR.is_dir():
        return []
    return sorted(JOURNALS_DIR.glob("*.json"))


# -- Raw API helpers -----------------------------------------------------------
# The SDK's request models drop ``None`` fields on serialization, which makes
# it impossible to *clear* a category (category_id: null). The bulk PATCH below
# sends a plain JSON body through the SDK's HTTP layer so nulls survive.

def _raw_request(client, method: str, resource_path: str, path_params: dict,
                 body: Optional[dict] = None) -> dict:
    api_client = client.api
    serialized = api_client.param_serialize(
        method=method,
        resource_path=resource_path,
        path_params=path_params,
        header_params={"Accept": "application/json", "Content-Type": "application/json"},
        body=body,
        auth_settings=["bearer"],
    )
    response = api_client.call_api(*serialized)
    response.read()
    payload = json.loads(response.data or b"{}")
    if response.status >= 400:
        detail = payload.get("error", payload)
        raise RuntimeError(f"YNAB API {response.status}: {detail}")
    return payload


def patch_transactions(client, updates: list[dict]) -> list[dict]:
    """Bulk-update transactions. Each update is ``{"id": ..., <field>: value}``.

    Returns the updated transaction objects from the API response.
    """
    payload = _raw_request(
        client, "PATCH", "/plans/{plan_id}/transactions",
        {"plan_id": client.budget_id},
        body={"transactions": updates},
    )
    return payload["data"]["transactions"]


def patch_month_category(client, month: str, category_id: str, budgeted: int) -> dict:
    api = ynab.CategoriesApi(client.api)
    wrapper = ynab.PatchMonthCategoryWrapper(
        category=ynab.SaveMonthCategory(budgeted=budgeted)
    )
    response = api.update_month_category(
        client.budget_id, date.fromisoformat(month), category_id, wrapper
    )
    return response.data.category.model_dump(mode="json", by_alias=True)


# -- Live-state lookups ----------------------------------------------------------

def fetch_live_transactions(client, ids: list[str], since_date: Optional[str] = None) -> dict:
    """Return ``{id: transaction}`` for the given ids, bypassing the cache."""
    wanted = set(ids)
    kwargs = {}
    if since_date:
        kwargs["since_date"] = since_date
    txns = client.get_transactions(ttl=0, **kwargs)
    return {t["id"]: t for t in txns if t["id"] in wanted}


def fetch_live_month(client, month: str) -> dict:
    """Return ``{category_id: category}`` for one month, bypassing the cache."""
    month_data = client.get_month(month, ttl=0)
    return {c["id"]: c for c in month_data["categories"]}


def _subset(txn: dict, fields=TRANSACTION_FIELDS) -> dict:
    return {f: txn.get(f) for f in fields}


# -- Apply ---------------------------------------------------------------------

def apply_transaction_changes(client, changes: list[dict], label: str, *,
                              plan_file: Optional[str] = None,
                              undo_of: Optional[str] = None,
                              batch_size: int = DEFAULT_BATCH_SIZE,
                              dry_run: bool = False,
                              force: bool = False,
                              since_date: Optional[str] = None) -> ChangeJournal:
    """Apply transaction field changes with live-state checks and journaling.

    Each change: ``{"id", "before": {field: value}, "after": {field: value},
    "context": {...}}``. Only the fields present in ``after`` are sent.
    """
    journal = ChangeJournal(label, client.budget_id, plan_file=plan_file, undo_of=undo_of)

    live = fetch_live_transactions(client, [c["id"] for c in changes], since_date)

    ready = []
    for change in changes:
        current = live.get(change["id"])
        if current is None:
            journal.skip(change, "transaction not found (deleted or outside window)")
            continue
        if current.get("deleted"):
            journal.skip(change, "transaction is deleted")
            continue
        already = all(current.get(f) == v for f, v in change["after"].items())
        if already:
            journal.skip(change, "already in target state")
            continue
        drift = {
            f: (change["before"].get(f), current.get(f))
            for f in change["after"]
            if f in change["before"] and change["before"].get(f) != current.get(f)
        }
        if drift and not force:
            journal.skip(change, f"live state differs from plan: {drift}")
            continue
        ready.append((change, current))

    for i in range(0, len(ready), batch_size):
        batch = ready[i:i + batch_size]
        updates = [{"id": c["id"], **c["after"]} for c, _ in batch]
        if dry_run:
            for change, current in batch:
                journal.record({**change, "before": _subset(current), "dry_run": True,
                                "verified": None})
            continue
        returned = {t["id"]: t for t in patch_transactions(client, updates)}
        for change, current in batch:
            result = returned.get(change["id"])
            verified = result is not None and all(
                result.get(f) == v for f, v in change["after"].items()
            )
            journal.record({
                **change,
                "before": _subset(current),
                "after_actual": _subset(result) if result else None,
                "verified": verified,
            })
        journal.flush()

    journal.flush()
    return journal


def apply_month_category_changes(client, changes: list[dict], label: str, *,
                                 plan_file: Optional[str] = None,
                                 undo_of: Optional[str] = None,
                                 dry_run: bool = False,
                                 force: bool = False) -> ChangeJournal:
    """Apply ``budgeted`` changes. Each change:
    ``{"month": "YYYY-MM-01", "category_id", "before": {"budgeted"}, "after": {"budgeted"}, "context"}``
    One API request per change — keep plans to a single month when possible
    (YNAB allows 200 requests per hour).
    """
    journal = ChangeJournal(label, client.budget_id, plan_file=plan_file, undo_of=undo_of)
    live_by_month: dict[str, dict] = {}

    for change in changes:
        month = change["month"]
        if month not in live_by_month:
            live_by_month[month] = fetch_live_month(client, month)
        current = live_by_month[month].get(change["category_id"])
        if current is None:
            journal.skip(change, "category not found in month")
            continue
        if current["budgeted"] != change["before"]["budgeted"] and not force:
            journal.skip(change, f"live budgeted {current['budgeted']} != plan {change['before']['budgeted']}")
            continue
        if current["budgeted"] == change["after"]["budgeted"]:
            journal.skip(change, "already in target state")
            continue
        if dry_run:
            journal.record({**change, "before": {"budgeted": current["budgeted"]},
                            "dry_run": True, "verified": None})
            continue
        result = patch_month_category(client, month, change["category_id"],
                                      change["after"]["budgeted"])
        journal.record({
            **change,
            "before": {"budgeted": current["budgeted"]},
            "after_actual": {"budgeted": result["budgeted"]},
            "verified": result["budgeted"] == change["after"]["budgeted"],
        })
        journal.flush()

    journal.flush()
    return journal


# -- Undo ----------------------------------------------------------------------

def undo_journal(client, journal_path: str | Path, *, dry_run: bool = False,
                 force: bool = False) -> ChangeJournal:
    """Reverse every applied entry in a journal (newest first)."""
    data = load_journal(journal_path)
    if data.get("budget_id") != client.budget_id:
        raise ValueError("journal belongs to a different budget")

    applied = [e for e in data["entries"] if not e.get("dry_run")]
    txn_changes, month_changes = [], []
    for entry in reversed(applied):
        reverse = {
            "id": entry.get("id"),
            "before": entry.get("after_actual") or entry["after"],
            "after": {f: entry["before"][f] for f in entry["after"]},
            "context": entry.get("context", {}),
        }
        if "month" in entry:
            reverse["month"] = entry["month"]
            reverse["category_id"] = entry["category_id"]
            month_changes.append(reverse)
        else:
            txn_changes.append(reverse)

    label = f"undo_{Path(journal_path).stem}"
    if month_changes:
        return apply_month_category_changes(
            client, month_changes, label, undo_of=journal_path, dry_run=dry_run, force=force
        )
    return apply_transaction_changes(
        client, txn_changes, label, undo_of=journal_path, dry_run=dry_run, force=force
    )


# -- Reporting -----------------------------------------------------------------

def summarize_journal(journal: ChangeJournal, dry_run: bool = False) -> str:
    entries = journal.entries
    verified = sum(1 for e in entries if e.get("verified"))
    failed = [e for e in entries if e.get("verified") is False]
    lines = []
    verb = "Would apply" if dry_run else "Applied"
    lines.append(f"{verb} {len(entries)} change(s); skipped {len(journal.data['skipped'])}.")
    if not dry_run:
        lines.append(f"Verified: {verified}/{len(entries)}")
        for e in failed:
            lines.append(f"  NOT VERIFIED: {e.get('id')} {e.get('context', {})}")
    for s in journal.data["skipped"][:20]:
        ctx = s.get("context", {})
        lines.append(f"  skipped {ctx.get('date', '')} {ctx.get('payee', ctx.get('category_name', ''))}: {s['reason']}")
    if len(journal.data["skipped"]) > 20:
        lines.append(f"  ... and {len(journal.data['skipped']) - 20} more skipped")
    lines.append(f"Journal: {journal.path}")
    if not dry_run and entries:
        lines.append(f"Undo with: --undo {journal.path}")
    return "\n".join(lines)
