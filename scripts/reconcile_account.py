#!/usr/bin/env python3
"""
Reconcile Account - bring an account's cleared balance to a target balance

Computes the difference between the account's cleared balance in YNAB and the
balance you give, prints the adjustment it would create, and creates it only
with --apply. Without --apply (the default) nothing is written.

The adjustment uses YNAB's own "Reconciliation Balance Adjustment" payee, is
dated today, and is created cleared as "reconciled" and approved, the way
YNAB's in-app reconcile records one. It does not mark the account's other
cleared transactions as reconciled.

Optional config.json section (all keys optional):

    "reconciliation": {
      "max_adjustment": 5000,
      "accounts": {
        "Brokerage": {"category": "Investments"},
        "Retirement": {"category": null}
      }
    }

- accounts: when present, only these accounts may be reconciled. "category"
  is the category name for the adjustment (null leaves it uncategorized,
  which is required for off-budget accounts).
- max_adjustment: the script refuses an adjustment larger than this, in
  dollars, in either direction.

Usage:
    uv run python scripts/reconcile_account.py "Account Name" 1234.56
    uv run python scripts/reconcile_account.py "Account Name" 1234.56 --apply
"""
import argparse
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from ynab_assistant import YNABClient, format_currency, load_config

EXIT_OK = 0
EXIT_REFUSED = 2


class ReconcileError(Exception):
    """A reason the adjustment cannot or must not be made."""


@dataclass
class Plan:
    account: dict
    target: int  # milliunits
    adjustment: int  # milliunits; 0 means nothing to do
    category_id: Optional[str]
    category_name: Optional[str]
    memo: str
    warnings: list


def parse_amount(text: str) -> int:
    """Parse a dollar amount like "7,295.67", "$45560.93" or "-12.5" to milliunits."""
    cleaned = text.strip().replace(",", "").replace("$", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ReconcileError(f"Not a dollar amount: {text!r}")
    if not value.is_finite():
        raise ReconcileError(f"Not a dollar amount: {text!r}")
    if value != value.quantize(Decimal("0.01")):
        raise ReconcileError(f"Amount has more than 2 decimal places: {text!r}")
    return int(value * 1000)


def find_account(accounts: list, name: str) -> dict:
    wanted = name.strip().casefold()
    matches = [
        a for a in accounts
        if a["name"].strip().casefold() == wanted and not a.get("deleted")
    ]
    if not matches:
        raise ReconcileError(f"No account named {name!r}")
    if len(matches) > 1:
        raise ReconcileError(f"More than one account named {name!r}")
    account = matches[0]
    if account.get("closed"):
        raise ReconcileError(f"Account {account['name']!r} is closed")
    return account


def find_category_id(category_groups: list, name: str) -> str:
    wanted = name.strip().casefold()
    matches = [
        c for group in category_groups if not group.get("deleted")
        for c in group.get("categories", [])
        if c["name"].strip().casefold() == wanted and not c.get("deleted")
    ]
    if not matches:
        raise ReconcileError(f"No category named {name!r}")
    if len(matches) > 1:
        raise ReconcileError(f"More than one category named {name!r}")
    return matches[0]["id"]


def account_rules(settings: dict, account_name: str) -> dict:
    """Return this account's config entry, enforcing the allow-list if one is set."""
    allowed = settings.get("accounts")
    if allowed is None:
        return {}
    for name, rules in allowed.items():
        if name.strip().casefold() == account_name.strip().casefold():
            return rules or {}
    raise ReconcileError(
        f"Account {account_name!r} is not in reconciliation.accounts in config.json "
        f"(allowed: {', '.join(sorted(allowed)) or 'none'})"
    )


def build_plan(
    accounts: list,
    category_groups: list,
    settings: dict,
    account_name: str,
    target: int,
    memo: Optional[str] = None,
) -> Plan:
    """Work out the adjustment. Raises ReconcileError when it must not be made."""
    rules = account_rules(settings, account_name)
    account = find_account(accounts, account_name)

    adjustment = target - account["cleared_balance"]

    warnings = []
    if account.get("uncleared_balance"):
        warnings.append(
            f"{format_currency(account['uncleared_balance'])} is uncleared. "
            "The target is compared with the cleared balance, as in YNAB's reconcile."
        )

    max_adjustment = settings.get("max_adjustment")
    if adjustment and max_adjustment is not None:
        cap = parse_amount(str(max_adjustment))
        if abs(adjustment) > cap:
            raise ReconcileError(
                f"Adjustment of {format_currency(adjustment)} exceeds the "
                f"{format_currency(cap)} cap (reconciliation.max_adjustment). "
                "Check the target balance, or raise the cap in config.json."
            )

    category_name = rules.get("category")
    category_id = None
    if category_name:
        if not account.get("on_budget"):
            raise ReconcileError(
                f"{account['name']!r} is off-budget, so its adjustment can't have a "
                f"category (config has {category_name!r})"
            )
        category_id = find_category_id(category_groups, category_name)

    if memo is None:
        memo = f"Reconciled to {format_currency(target)} (reconcile_account.py)"

    return Plan(
        account=account,
        target=target,
        adjustment=adjustment,
        category_id=category_id,
        category_name=category_name,
        memo=memo,
        warnings=warnings,
    )


def describe(plan: Plan) -> str:
    account = plan.account
    lines = [
        f"Account:         {account['name']} ({'on' if account.get('on_budget') else 'off'}-budget)",
        f"Cleared balance: {format_currency(account['cleared_balance'])}",
        f"Target balance:  {format_currency(plan.target)}",
    ]
    if plan.adjustment == 0:
        lines.append("Adjustment:      none, the cleared balance already matches")
    else:
        sign = "+" if plan.adjustment > 0 else "-"
        lines += [
            f"Adjustment:      {sign}{format_currency(abs(plan.adjustment))}",
            f"Category:        {plan.category_name or 'none (uncategorized)'}",
            f"Date:            {date.today().isoformat()}",
            f"Memo:            {plan.memo}",
        ]
    lines += [f"Warning: {w}" for w in plan.warnings]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Bring an account's cleared balance to a target with one adjustment. "
                    "Dry run unless --apply is given."
    )
    parser.add_argument("account", help="Account name, as in YNAB")
    parser.add_argument("balance", help="Target balance in dollars, e.g. 7295.67")
    parser.add_argument("--apply", action="store_true",
                        help="Create the adjustment in YNAB (default: dry run)")
    parser.add_argument("--memo", help="Memo for the adjustment")
    args = parser.parse_args(argv)

    settings = load_config().get("reconciliation", {})
    # Balances must be current, so skip the read cache
    client = YNABClient(use_cache=False)

    try:
        target = parse_amount(args.balance)
        accounts = client.get_accounts()
        rules = account_rules(settings, args.account)
        category_groups = client.get_categories() if rules.get("category") else []
        plan = build_plan(accounts, category_groups, settings,
                          args.account, target, memo=args.memo)
        payee = client.get_reconciliation_payee() if plan.adjustment else None
        if plan.adjustment and payee is None:
            raise ReconcileError(
                "YNAB's 'Reconciliation Balance Adjustment' payee was not found. "
                "Reconcile any account once in the YNAB app to create it."
            )
    except ReconcileError as e:
        print(f"Refused: {e}", file=sys.stderr)
        return EXIT_REFUSED

    print(describe(plan))
    if plan.adjustment == 0:
        return EXIT_OK

    if not args.apply:
        print("\nDry run: nothing was written. Re-run with --apply to create it.")
        return EXIT_OK

    created = client.create_transaction(
        plan.account["id"],
        plan.adjustment,
        payee_id=payee["id"],
        category_id=plan.category_id,
        memo=plan.memo,
        cleared="reconciled",
        approved=True,
    )
    print(f"\nCreated adjustment {created['id']}.")

    refreshed = find_account(client.get_accounts(), plan.account["name"])
    print(f"Cleared balance is now {format_currency(refreshed['cleared_balance'])}.")
    if refreshed["cleared_balance"] != plan.target:
        print("Warning: the cleared balance does not match the target. Check the account in YNAB.",
              file=sys.stderr)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
