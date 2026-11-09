"""Tests for scripts/reconcile_account.py and the YNABClient write helpers.

Nothing here talks to YNAB: the client's SDK APIs are replaced with mocks.
"""
import importlib.util
from datetime import date
from pathlib import Path
from unittest import mock

import pytest

from ynab_assistant import client as client_module
from ynab_assistant.client import YNABClient, RECONCILIATION_PAYEE_NAME

SCRIPT = Path(__file__).parent.parent / "scripts" / "reconcile_account.py"
spec = importlib.util.spec_from_file_location("reconcile_account", SCRIPT)
reconcile = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reconcile)

ACCOUNT_ID = "11111111-1111-1111-1111-111111111111"
CATEGORY_ID = "22222222-2222-2222-2222-222222222222"
PAYEE_ID = "33333333-3333-3333-3333-333333333333"


def account(name="Brokerage", cleared=7_000_000, uncleared=0, on_budget=True, **kw):
    return {
        "id": ACCOUNT_ID, "name": name, "on_budget": on_budget, "closed": False,
        "deleted": False, "cleared_balance": cleared, "uncleared_balance": uncleared,
        "balance": cleared + uncleared, **kw,
    }


CATEGORIES = [{
    "name": "Savings", "deleted": False,
    "categories": [{"id": CATEGORY_ID, "name": "Down Payment Fund", "deleted": False}],
}]


# -- parse_amount -------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("7295.67", 7_295_670),
    ("$45,560.93", 45_560_930),
    ("-12.5", -12_500),
    ("0", 0),
])
def test_parse_amount(text, expected):
    assert reconcile.parse_amount(text) == expected


@pytest.mark.parametrize("text", ["abc", "1.234", "", "nan", "inf"])
def test_parse_amount_rejects(text):
    with pytest.raises(reconcile.ReconcileError):
        reconcile.parse_amount(text)


# -- build_plan ---------------------------------------------------------------

def test_plan_computes_signed_difference():
    plan = reconcile.build_plan([account(cleared=7_000_000)], [], {}, "Brokerage", 7_295_670)
    assert plan.adjustment == 295_670
    plan = reconcile.build_plan([account(cleared=7_500_000)], [], {}, "brokerage", 7_295_670)
    assert plan.adjustment == -204_330


def test_plan_zero_when_balanced():
    plan = reconcile.build_plan([account(cleared=7_295_670)], [], {}, "Brokerage", 7_295_670)
    assert plan.adjustment == 0


def test_plan_uses_configured_category():
    settings = {"accounts": {"Brokerage": {"category": "Down Payment Fund"}}}
    plan = reconcile.build_plan([account()], CATEGORIES, settings, "Brokerage", 7_100_000)
    assert plan.category_id == CATEGORY_ID


def test_plan_null_category_stays_uncategorized():
    settings = {"accounts": {"Roth": {"category": None}}}
    plan = reconcile.build_plan([account("Roth", on_budget=False)], [], settings, "Roth", 7_100_000)
    assert plan.category_id is None


def test_plan_refuses_account_not_in_allow_list():
    settings = {"accounts": {"Roth": {"category": None}}}
    with pytest.raises(reconcile.ReconcileError, match="not in reconciliation.accounts"):
        reconcile.build_plan([account()], [], settings, "Brokerage", 1)


def test_plan_refuses_category_on_off_budget_account():
    settings = {"accounts": {"Roth": {"category": "Down Payment Fund"}}}
    with pytest.raises(reconcile.ReconcileError, match="off-budget"):
        reconcile.build_plan([account("Roth", on_budget=False)], CATEGORIES, settings, "Roth", 1)


def test_plan_refuses_unknown_closed_or_ambiguous_account():
    with pytest.raises(reconcile.ReconcileError, match="No account"):
        reconcile.build_plan([account()], [], {}, "Nope", 1)
    with pytest.raises(reconcile.ReconcileError, match="closed"):
        reconcile.build_plan([account(closed=True)], [], {}, "Brokerage", 1)
    with pytest.raises(reconcile.ReconcileError, match="More than one"):
        reconcile.build_plan([account(), account()], [], {}, "Brokerage", 1)


def test_plan_refuses_unknown_category():
    settings = {"accounts": {"Brokerage": {"category": "Nope"}}}
    with pytest.raises(reconcile.ReconcileError, match="No category"):
        reconcile.build_plan([account()], CATEGORIES, settings, "Brokerage", 1)


def test_plan_warns_about_uncleared():
    plan = reconcile.build_plan([account(uncleared=-5_000)], [], {}, "Brokerage", 7_000_000)
    assert plan.warnings and "uncleared" in plan.warnings[0]


# -- main: dry run vs apply ---------------------------------------------------

@pytest.fixture
def fake_client(monkeypatch):
    fake = mock.Mock()
    fake.get_accounts.return_value = [account(cleared=7_000_000)]
    fake.get_categories.return_value = CATEGORIES
    fake.get_reconciliation_payee.return_value = {"id": PAYEE_ID, "name": RECONCILIATION_PAYEE_NAME}
    fake.create_transaction.return_value = {"id": "new-txn"}
    monkeypatch.setattr(reconcile, "YNABClient", lambda **kw: fake)
    monkeypatch.setattr(reconcile, "load_config", lambda: {"reconciliation": {
        "accounts": {"Brokerage": {"category": "Down Payment Fund"}},
    }})
    return fake


def test_main_dry_run_writes_nothing(fake_client, capsys):
    assert reconcile.main(["Brokerage", "7295.67"]) == reconcile.EXIT_OK
    fake_client.create_transaction.assert_not_called()
    out = capsys.readouterr().out
    assert "+$295.67" in out and "Dry run" in out


def test_main_apply_creates_adjustment(fake_client):
    fake_client.get_accounts.side_effect = [
        [account(cleared=7_000_000)], [account(cleared=7_295_670)],
    ]
    assert reconcile.main(["Brokerage", "7295.67", "--apply"]) == reconcile.EXIT_OK
    fake_client.create_transaction.assert_called_once_with(
        ACCOUNT_ID, 295_670, payee_id=PAYEE_ID, category_id=CATEGORY_ID,
        memo=mock.ANY, cleared="reconciled", approved=True,
    )


def test_main_refusal_writes_nothing(fake_client, capsys):
    assert reconcile.main(["Retirement", "9000", "--apply"]) == reconcile.EXIT_REFUSED
    fake_client.create_transaction.assert_not_called()
    assert "Refused" in capsys.readouterr().err


def test_main_refuses_malformed_amount(fake_client):
    assert reconcile.main(["Brokerage", "7295.678", "--apply"]) == reconcile.EXIT_REFUSED
    fake_client.create_transaction.assert_not_called()


def test_main_refuses_without_reconciliation_payee(fake_client):
    fake_client.get_reconciliation_payee.return_value = None
    assert reconcile.main(["Brokerage", "7295.67", "--apply"]) == reconcile.EXIT_REFUSED
    fake_client.create_transaction.assert_not_called()


# -- YNABClient write helpers -------------------------------------------------

@pytest.fixture
def ynab_client(monkeypatch, tmp_path):
    monkeypatch.setattr(client_module, "API_CACHE_DIR", tmp_path)
    c = YNABClient.__new__(YNABClient)
    c.budget_id = "budget"
    c.use_cache = True
    c.cache_stats = {"hits": 0, "misses": 0}
    c._transactions_api = mock.Mock()
    c._payees_api = mock.Mock()
    return c


def test_create_transaction_builds_sdk_model_and_clears_cache(ynab_client, tmp_path):
    (tmp_path / "stale.json").write_text("[]")
    response = mock.Mock()
    response.data.transaction = {"id": "t1"}
    ynab_client._transactions_api.create_transaction.return_value = response

    result = ynab_client.create_transaction(
        ACCOUNT_ID, -204_330, payee_id=PAYEE_ID, category_id=CATEGORY_ID,
        memo="m", cleared="reconciled", approved=True,
    )

    assert result == {"id": "t1"}
    budget_id, wrapper = ynab_client._transactions_api.create_transaction.call_args.args
    txn = wrapper.transaction
    assert budget_id == "budget"
    assert str(txn.account_id) == ACCOUNT_ID and txn.amount == -204_330
    assert str(txn.payee_id) == PAYEE_ID and str(txn.category_id) == CATEGORY_ID
    assert txn.cleared.value == "reconciled" and txn.approved is True
    assert txn.var_date == date.today()
    assert not list(tmp_path.glob("*.json"))


def test_get_reconciliation_payee(ynab_client):
    payees = [
        {"id": "a", "name": "Grocer", "deleted": False},
        {"id": "b", "name": RECONCILIATION_PAYEE_NAME, "deleted": True},
        {"id": "c", "name": RECONCILIATION_PAYEE_NAME, "deleted": False},
    ]
    with mock.patch.object(YNABClient, "get_payees", return_value=payees):
        assert ynab_client.get_reconciliation_payee()["id"] == "c"
    with mock.patch.object(YNABClient, "get_payees", return_value=payees[:2]):
        assert ynab_client.get_reconciliation_payee() is None
