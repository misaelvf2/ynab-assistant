#!/usr/bin/env python3
"""
Monthly Retrospective - Comprehensive end-of-month financial report with letter grade
"""
import argparse
from collections import defaultdict
from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from ynab_assistant import (
    YNABClient, format_currency, get_month_string,
    milliunits_to_dollars, save_report
)


def get_previous_month():
    """Returns (year, month) for the previous month."""
    prev = date.today() - relativedelta(months=1)
    return prev.year, prev.month


def calculate_income(transactions):
    """Sum inflows where category is 'Inflow: Ready to Assign' and not a transfer."""
    total = 0
    for txn in transactions:
        if txn["deleted"]:
            continue
        if txn["category_name"] == "Inflow: Ready to Assign" and txn["transfer_account_id"] is None:
            total += txn["amount"]
    return total


def build_spending_overview(categories):
    """Group spending by category group, skip internal/credit card/hidden groups."""
    skip_groups = {"Internal Master Category", "Credit Card Payments", "Hidden Categories"}

    groups = defaultdict(lambda: {"budgeted": 0, "spent": 0, "categories": []})
    for cat in categories:
        if cat["deleted"] or cat["hidden"]:
            continue
        group = cat["category_group_name"]
        if group in skip_groups:
            continue
        if cat["budgeted"] == 0 and cat["activity"] == 0:
            continue

        spent = -cat["activity"]
        groups[group]["budgeted"] += cat["budgeted"]
        groups[group]["spent"] += spent
        groups[group]["categories"].append({
            "name": cat["name"],
            "budgeted": cat["budgeted"],
            "spent": spent,
        })

    return dict(groups)


def build_eating_out_section(client, month_str, config):
    """Fetch eating out category and compare against hard cap."""
    eating_out_config = config["spending_caps"]["eating_out"]
    monthly_cap = eating_out_config["monthly_limit"]
    category_id = eating_out_config["category_id"]

    category = client.get_category_by_month(category_id, month_str)
    spent = -milliunits_to_dollars(category["activity"])
    budgeted = milliunits_to_dollars(category["budgeted"])

    return {
        "spent": spent,
        "budgeted": budgeted,
        "cap": monthly_cap,
        "over": spent > monthly_cap,
        "remaining": monthly_cap - spent,
        "pct_of_cap": (spent / monthly_cap * 100) if monthly_cap > 0 else 0,
    }


def build_savings_section(categories):
    """Filter for savings/fund categories. Budgeted = saved, activity = withdrawn."""
    savings_keywords = {"fund", "savings", "emergency", "down payment", "vacation"}
    savings = []

    for cat in categories:
        if cat["deleted"] or cat["hidden"]:
            continue
        name_lower = cat["name"].lower()
        if any(kw in name_lower for kw in savings_keywords):
            budgeted = cat["budgeted"]
            activity = cat["activity"]
            if budgeted == 0 and activity == 0:
                continue
            savings.append({
                "name": cat["name"],
                "budgeted": budgeted,
                "activity": activity,
            })

    return savings


def reconstruct_net_worth(client, year, month):
    """Reconstruct end-of-month net worth by walking backwards from current balances.

    Same algorithm as net_worth_history.py:reconstruct_account_history.
    """
    accounts = client.get_accounts()
    target_month = f"{year:04d}-{month:02d}"

    # Build list of all months from target to current
    today = date.today()
    current_month_dt = datetime(year, month, 1)
    end_month_dt = datetime(today.year, today.month, 1)

    all_months = []
    dt = current_month_dt
    while dt <= end_month_dt:
        all_months.append(dt.strftime("%Y-%m"))
        dt += relativedelta(months=1)

    assets = 0
    liabilities = 0

    for acc in accounts:
        if acc["closed"] or acc["deleted"]:
            continue

        current_balance = acc["balance"]
        txns = client.get_account_transactions(acc["id"])

        txns_by_month = defaultdict(list)
        for txn in txns:
            if txn["deleted"]:
                continue
            m = txn["date"][:7]
            txns_by_month[m].append(txn)

        # Walk backwards from current balance
        running_balance = current_balance
        target_balance = current_balance

        for m in reversed(all_months):
            target_balance = running_balance
            for txn in txns_by_month.get(m, []):
                running_balance -= txn["amount"]

        # target_balance is the balance at end of target_month
        if target_balance >= 0:
            assets += target_balance
        else:
            liabilities += abs(target_balance)

    net_worth = assets - liabilities
    return {"assets": assets, "liabilities": liabilities, "net_worth": net_worth}


def build_notable_transactions(transactions, config):
    """Flag large transactions (>$500), uncategorized, and missing memos (>$100)."""
    large_threshold = config["review_settings"]["flag_large_transactions_above"]
    memo_threshold = config["review_settings"]["require_memo_for_transactions_above"]

    large_threshold_mu = int(large_threshold * 1000)
    memo_threshold_mu = int(memo_threshold * 1000)

    large = []
    uncategorized = []
    missing_memo = []

    for txn in transactions:
        if txn["deleted"] or txn["transfer_account_id"] is not None:
            continue

        abs_amount = abs(txn["amount"])

        if abs_amount >= large_threshold_mu and txn["amount"] < 0:
            large.append(txn)

        if (txn["category_name"] == "Uncategorized" or txn["category_id"] is None) and txn["amount"] < 0:
            uncategorized.append(txn)

        if abs_amount >= memo_threshold_mu and not txn["memo"]:
            missing_memo.append(txn)

    return {
        "large": sorted(large, key=lambda x: x["amount"]),
        "uncategorized": uncategorized,
        "missing_memo": missing_memo,
    }


def build_cash_flow_analysis(income, total_spent, total_saved):
    """Prose analysis of where the money went."""
    income_d = milliunits_to_dollars(income)
    spent_d = milliunits_to_dollars(total_spent)
    saved_d = milliunits_to_dollars(total_saved)

    lines = []

    if income_d <= 0:
        lines.append("No income recorded this month, so there's not much to analyze on the cash flow front.")
        return "\n".join(lines)

    spending_rate = spent_d / income_d * 100 if income_d > 0 else 0
    savings_rate = saved_d / income_d * 100 if income_d > 0 else 0
    net_remainder = income_d - spent_d

    lines.append(
        f"You brought in ${income_d:,.0f} and spent ${spent_d:,.0f}, "
        f"consuming {spending_rate:.0f}% of your income on expenses."
    )

    if net_remainder > 0:
        lines.append(
            f"That leaves ${net_remainder:,.0f} of net inflow after spending."
        )
    else:
        lines.append(
            f"You actually spent ${abs(net_remainder):,.0f} more than you earned. "
            f"That gap came from somewhere—savings drawdowns, credit, or money budgeted from prior months."
        )

    if savings_rate >= 30:
        lines.append(
            f"Your savings rate was {savings_rate:.0f}% of income—aggressive and ahead of most benchmarks. "
            f"The standard advice is 20%. You're beating it."
        )
    elif savings_rate >= 20:
        lines.append(
            f"Savings rate: {savings_rate:.0f}% of income. That hits the commonly cited 20% target. "
            f"Not extraordinary, but you're doing what the textbooks say."
        )
    elif savings_rate >= 10:
        lines.append(
            f"Savings rate: {savings_rate:.0f}% of income. Below the 20% guideline. "
            f"You're saving something, which is more than many people manage, but there's meaningful room to improve."
        )
    elif savings_rate > 0:
        lines.append(
            f"Savings rate: {savings_rate:.0f}% of income. That's thin. "
            f"At this rate you're barely building a buffer, let alone making progress on long-term goals."
        )
    else:
        lines.append(
            f"No money went into savings categories this month. "
            f"If this is a one-off, fine. If it's a pattern, you're living paycheck to paycheck by choice."
        )

    return "\n".join(lines)


def build_spending_analysis(spending, total_spent, total_budgeted):
    """Prose analysis of spending patterns—over/under categories, what's driving the numbers."""
    lines = []
    spent_d = milliunits_to_dollars(total_spent)
    budgeted_d = milliunits_to_dollars(total_budgeted)

    if total_budgeted > 0:
        ratio = total_spent / total_budgeted
        if ratio <= 0.70:
            lines.append(
                f"You used {ratio * 100:.0f}% of your total budget. "
                f"Significant underspend—either you're being disciplined or the budget is inflated. "
                f"If categories are consistently funded but unspent, consider reallocating to savings."
            )
        elif ratio <= 0.90:
            lines.append(
                f"Overall spending came in at {ratio * 100:.0f}% of budget. "
                f"Healthy margin. You stayed within bounds and kept some breathing room."
            )
        elif ratio <= 1.0:
            lines.append(
                f"You used {ratio * 100:.0f}% of your budget—cutting it close, but technically within limits."
            )
        else:
            over_amount = spent_d - budgeted_d
            lines.append(
                f"You exceeded your budget by ${over_amount:,.0f}, spending {ratio * 100:.0f}% of the allocated amount. "
                f"That's real money that had to come from somewhere—probably stealing from future months."
            )

    # Find notable groups
    over_groups = []
    under_groups = []
    for group_name, gd in spending.items():
        if gd["budgeted"] <= 0:
            continue
        gratio = gd["spent"] / gd["budgeted"]
        if gratio > 1.05:
            over_groups.append((group_name, gratio, gd["spent"], gd["budgeted"]))
        elif gratio < 0.50 and gd["budgeted"] > 100000:  # >$100 budgeted
            under_groups.append((group_name, gratio, gd["spent"], gd["budgeted"]))

    if over_groups:
        parts = []
        for name, r, s, b in over_groups:
            parts.append(
                f"{name} ({milliunits_to_dollars(s):,.0f}/{milliunits_to_dollars(b):,.0f}, {r * 100:.0f}%)"
            )
        lines.append(
            f"Over-budget groups: {', '.join(parts)}. "
            f"These are the areas pulling your overall numbers down."
        )

    if under_groups:
        parts = []
        for name, r, s, b in under_groups:
            parts.append(f"{name} ({r * 100:.0f}% used)")
        lines.append(
            f"Significantly under-budget: {', '.join(parts)}. "
            f"Good if intentional—wasteful budgeting if not."
        )

    # Find biggest spending categories
    all_cats = []
    for gd in spending.values():
        all_cats.extend(gd["categories"])
    all_cats.sort(key=lambda x: x["spent"], reverse=True)

    if all_cats and total_spent > 0:
        top = all_cats[0]
        top_pct = top["spent"] / total_spent * 100
        lines.append(
            f"Your single largest category was {top['name']} at "
            f"{format_currency(top['spent'])} ({top_pct:.0f}% of all spending)."
        )

        # Concentration: top 3 categories as % of total
        top3 = all_cats[:3]
        top3_total = sum(c["spent"] for c in top3)
        top3_pct = top3_total / total_spent * 100
        top3_names = ", ".join(c["name"] for c in top3)
        lines.append(
            f"Your top 3 categories ({top3_names}) accounted for {top3_pct:.0f}% of total spending. "
        )
        if top3_pct > 70:
            lines.append(
                "Spending is highly concentrated—a few big items are driving the month."
            )
        elif top3_pct > 50:
            lines.append(
                "Moderately concentrated. A mix of fixed costs and discretionary spending."
            )
        else:
            lines.append(
                "Spending is spread across many categories. No single area dominates."
            )

    return "\n".join(lines)


def build_eating_out_analysis(eating_out):
    """Curmudgeonly narrative about the eating out situation."""
    spent = eating_out["spent"]
    cap = eating_out["cap"]
    pct = eating_out["pct_of_cap"]

    if spent > cap * 1.5:
        return (
            f"You spent ${spent:,.0f} eating out—that's {pct:.0f}% of your ${cap:.0f} cap. "
            f"Nearly double the limit. At this point, the cap is a suggestion you're actively ignoring. "
            f"A month of home cooking wouldn't kill you. It might even be character-building."
        )
    elif spent > cap:
        over = spent - cap
        return (
            f"${spent:,.0f} on restaurants, ${over:,.0f} over the ${cap:.0f} cap. "
            f"Every dollar over that line is money you explicitly said you wouldn't spend. "
            f"If the cap is unrealistic, raise it and own it. If it's realistic, stick to it."
        )
    elif spent > cap * 0.9:
        return (
            f"${spent:,.0f} spent eating out, {pct:.0f}% of your ${cap:.0f} cap. "
            f"Technically under, but barely. You have ${cap - spent:,.0f} of slack, "
            f"which is one nice dinner. This isn't a comfortable margin."
        )
    elif spent > cap * 0.7:
        return (
            f"${spent:,.0f} on eating out ({pct:.0f}% of cap). "
            f"Reasonable. You're using the budget without abusing it. "
            f"Don't let that become permission to blow it next month."
        )
    elif spent > 0:
        return (
            f"Only ${spent:,.0f} on eating out ({pct:.0f}% of cap). Restrained. "
            f"Either you were disciplined or you were too busy to eat out. "
            f"Either way, the numbers are clean."
        )
    else:
        return (
            f"Zero spent eating out. Either you're on a monk-mode budget challenge, "
            f"or the data's wrong. If it's real, congratulations—your kitchen got some use."
        )


def build_savings_analysis(savings, total_saved, income):
    """Commentary on savings rate and individual fund performance."""
    lines = []
    saved_d = milliunits_to_dollars(total_saved)
    income_d = milliunits_to_dollars(income)

    if not savings:
        return "No savings or fund categories had activity this month. That's a problem worth addressing."

    total_withdrawn = 0
    for s in savings:
        total_withdrawn += -s["activity"]
    withdrawn_d = milliunits_to_dollars(total_withdrawn)

    net_savings = saved_d - withdrawn_d
    lines.append(
        f"You earmarked ${saved_d:,.0f} across savings categories and withdrew ${withdrawn_d:,.0f}, "
        f"for a net savings contribution of ${net_savings:,.0f}."
    )

    if net_savings < 0:
        lines.append(
            f"You pulled more out of savings than you put in. "
            f"That can be fine for planned expenses—vacations, big purchases—but if it becomes the norm, "
            f"your safety net is shrinking."
        )
    elif net_savings == 0 and saved_d > 0:
        lines.append(
            "You put in exactly what you took out. Treading water. "
            "The savings balance didn't shrink, but it didn't grow either."
        )
    elif saved_d > 0 and withdrawn_d == 0:
        lines.append(
            "All contributions, no withdrawals. The ideal month for your savings accounts."
        )

    # Per-fund commentary
    for s in savings:
        name = s["name"]
        budgeted_d = milliunits_to_dollars(s["budgeted"])
        activity_d = milliunits_to_dollars(-s["activity"])

        if budgeted_d > 0 and activity_d == 0:
            lines.append(f"**{name}:** ${budgeted_d:,.0f} saved, nothing withdrawn. Solid.")
        elif budgeted_d > 0 and activity_d > 0:
            if activity_d > budgeted_d:
                lines.append(
                    f"**{name}:** ${budgeted_d:,.0f} contributed but ${activity_d:,.0f} withdrawn—"
                    f"net drawdown of ${activity_d - budgeted_d:,.0f}. "
                    f"Hopefully this was for the fund's intended purpose."
                )
            else:
                lines.append(
                    f"**{name}:** ${budgeted_d:,.0f} in, ${activity_d:,.0f} out. "
                    f"Still net positive by ${budgeted_d - activity_d:,.0f}."
                )
        elif budgeted_d == 0 and activity_d > 0:
            lines.append(
                f"**{name}:** No new contributions, ${activity_d:,.0f} withdrawn. "
                f"Spending down the fund without replenishing it."
            )

    return "\n".join(lines)


def build_net_worth_analysis(nw_current, nw_previous, nw_delta, income):
    """Narrative about net worth movement for the month."""
    lines = []
    delta_d = milliunits_to_dollars(nw_delta)
    current_d = milliunits_to_dollars(nw_current["net_worth"])
    prev_d = milliunits_to_dollars(nw_previous["net_worth"])
    income_d = milliunits_to_dollars(income)

    assets_d = milliunits_to_dollars(nw_current["assets"])
    liab_d = milliunits_to_dollars(nw_current["liabilities"])
    prev_assets_d = milliunits_to_dollars(nw_previous["assets"])
    prev_liab_d = milliunits_to_dollars(nw_previous["liabilities"])
    asset_delta = assets_d - prev_assets_d
    liab_delta = liab_d - prev_liab_d

    pct_change = (nw_delta / nw_previous["net_worth"] * 100) if nw_previous["net_worth"] != 0 else 0

    if delta_d > 0:
        lines.append(
            f"Net worth grew by ${delta_d:,.0f} ({pct_change:+.1f}%), ending the month at ${current_d:,.0f}."
        )
    elif delta_d < 0:
        lines.append(
            f"Net worth declined by ${abs(delta_d):,.0f} ({pct_change:+.1f}%), ending at ${current_d:,.0f}."
        )
    else:
        lines.append(f"Net worth held flat at ${current_d:,.0f}.")

    # Break down what drove the change
    if asset_delta != 0 or liab_delta != 0:
        parts = []
        if asset_delta > 0:
            parts.append(f"assets grew by ${asset_delta:,.0f}")
        elif asset_delta < 0:
            parts.append(f"assets fell by ${abs(asset_delta):,.0f}")

        if liab_delta < 0:
            parts.append(f"liabilities dropped by ${abs(liab_delta):,.0f}")
        elif liab_delta > 0:
            parts.append(f"liabilities increased by ${liab_delta:,.0f}")

        if parts:
            lines.append(f"Breakdown: {', and '.join(parts)}.")

    # Asset-to-liability ratio
    if liab_d > 0:
        ratio = assets_d / liab_d
        lines.append(
            f"Your asset-to-liability ratio is {ratio:.1f}:1. "
        )
        if ratio > 10:
            lines.append(
                "Liabilities are a small fraction of your balance sheet—"
                "solid structural position."
            )
        elif ratio > 3:
            lines.append(
                "Comfortable leverage. Debt is manageable relative to assets."
            )
        elif ratio > 1.5:
            lines.append(
                "Adequate, but liabilities are a meaningful share of the picture. Watch the trend."
            )
        else:
            lines.append(
                "Liabilities are large relative to assets. Focus on reducing debt or building asset value."
            )
    else:
        lines.append("No liabilities on the books. Debt-free status—maintain it.")

    # Net worth relative to income
    if income_d > 0 and delta_d != 0:
        nw_to_income = delta_d / income_d * 100
        if delta_d > 0:
            lines.append(
                f"Your net worth grew by {nw_to_income:.0f}% of this month's income. "
            )
            if nw_to_income > 100:
                lines.append(
                    "More than your entire paycheck went to net worth growth—"
                    "likely helped by investment gains or asset appreciation."
                )
            elif nw_to_income > 50:
                lines.append(
                    "More than half your income translated to wealth building. Strong conversion."
                )
        else:
            lines.append(
                f"You lost {abs(nw_to_income):.0f}% of a month's income in net worth. "
                f"Some months are like that, but make sure it's not a habit."
            )

    return "\n".join(lines)


def build_grade_analysis(grade, metrics):
    """Explain each grade dimension with prose, not just numbers."""
    lines = []
    scores = grade["scores"]

    # Budget Adherence
    ba_score = scores["Budget Adherence"]
    total_spent = metrics["total_spent"]
    total_budgeted = metrics["total_budgeted"]
    if total_budgeted > 0:
        ratio = total_spent / total_budgeted
        lines.append(
            f"**Budget Adherence ({ba_score}/30):** "
            f"You spent {ratio * 100:.0f}% of your total budget. "
        )
        if ba_score >= 25:
            lines.append("Well within bounds. This is what budget discipline looks like.")
        elif ba_score >= 20:
            lines.append("Close to the line but still under. Tighter months leave less room for error.")
        elif ba_score >= 12:
            lines.append("Over budget. The budget exists for a reason—this dimension dragged your grade down.")
        else:
            lines.append("Significantly over budget. At this point, either the budget is fiction or spending is out of control.")
    else:
        lines.append(f"**Budget Adherence ({ba_score}/30):** No budget set. Can't measure what you don't track.")

    # Eating Out
    eo_score = scores["Eating Out Discipline"]
    eo_spent = metrics["eating_out_spent"]
    eo_cap = metrics["eating_out_cap"]
    eo_ratio = eo_spent / eo_cap if eo_cap > 0 else 0
    lines.append(
        f"**Eating Out Discipline ({eo_score}/25):** "
        f"${eo_spent:,.0f} against a ${eo_cap:.0f} cap ({eo_ratio * 100:.0f}%). "
    )
    if eo_score >= 22:
        lines.append("Well-controlled. The cap is doing its job.")
    elif eo_score >= 18:
        lines.append("Under the cap but not by much. You're managing, barely.")
    elif eo_score >= 10:
        lines.append("Over the cap. Every time you exceed this, the rule loses meaning.")
    else:
        lines.append("Way over. The eating out cap needs to either be enforced or honestly revised.")

    # Savings
    sav_score = scores["Savings Contributions"]
    saved_d = milliunits_to_dollars(metrics["total_saved"])
    lines.append(
        f"**Savings Contributions ({sav_score}/25):** "
        f"${saved_d:,.0f} earmarked for savings/funds. "
    )
    if sav_score >= 22:
        lines.append("Strong savings month. This is how you build wealth over time.")
    elif sav_score >= 18:
        lines.append("Decent. You're contributing, though more would accelerate your goals.")
    elif sav_score >= 12:
        lines.append("Modest savings. Better than nothing, but not enough to move the needle quickly.")
    elif sav_score > 0:
        lines.append("Minimal. At this level, it'll take a long time to reach any meaningful goal.")
    else:
        lines.append("Nothing saved. Every month at zero is a month your future self won't get back.")

    # Hygiene
    hyg_score = scores["Transaction Hygiene"]
    uncat = metrics["uncategorized_count"]
    missing = metrics["missing_memo_count"]
    lines.append(
        f"**Transaction Hygiene ({hyg_score}/20):** "
    )
    if hyg_score == 20:
        lines.append(
            "Clean books. Every transaction categorized, memos where they should be. "
            "This is table stakes for knowing where your money goes."
        )
    else:
        parts = []
        if uncat > 0:
            parts.append(f"{uncat} uncategorized transaction{'s' if uncat != 1 else ''}")
        if missing > 0:
            parts.append(f"{missing} missing memo{'s' if missing != 1 else ''}")
        lines.append(
            f"{', '.join(parts)}. "
            f"Each one is a blind spot in your financial picture. "
            f"It only takes a few minutes to fix—do it before the next month starts."
        )

    return "\n\n".join(lines)


def calculate_grade(metrics):
    """Score across 4 dimensions, return letter grade + breakdown.

    Dimensions (100 points total):
      Budget Adherence: 30 pts  (total spent / total budgeted ratio)
      Eating Out:       25 pts  (spend vs $600 cap)
      Savings:          25 pts  (total budgeted in savings categories)
      Hygiene:          20 pts  (deduct per uncategorized / missing memo)
    """
    scores = {}

    # Budget Adherence (30 pts)
    total_spent = metrics.get("total_spent", 0)
    total_budgeted = metrics.get("total_budgeted", 0)
    if total_budgeted > 0:
        ratio = total_spent / total_budgeted
        if ratio <= 0.85:
            scores["Budget Adherence"] = 30
        elif ratio <= 0.95:
            scores["Budget Adherence"] = 25
        elif ratio <= 1.0:
            scores["Budget Adherence"] = 20
        elif ratio <= 1.1:
            scores["Budget Adherence"] = 12
        elif ratio <= 1.25:
            scores["Budget Adherence"] = 6
        else:
            scores["Budget Adherence"] = 0
    else:
        scores["Budget Adherence"] = 15  # no budget set—half credit

    # Eating Out Discipline (25 pts)
    eating_out_spent = metrics.get("eating_out_spent", 0)
    eating_out_cap = metrics.get("eating_out_cap", 600)
    if eating_out_cap > 0:
        eo_ratio = eating_out_spent / eating_out_cap
        if eo_ratio <= 0.7:
            scores["Eating Out Discipline"] = 25
        elif eo_ratio <= 0.85:
            scores["Eating Out Discipline"] = 22
        elif eo_ratio <= 1.0:
            scores["Eating Out Discipline"] = 18
        elif eo_ratio <= 1.15:
            scores["Eating Out Discipline"] = 10
        elif eo_ratio <= 1.3:
            scores["Eating Out Discipline"] = 5
        else:
            scores["Eating Out Discipline"] = 0
    else:
        scores["Eating Out Discipline"] = 12

    # Savings Contributions (25 pts)
    total_saved = metrics.get("total_saved", 0)
    total_saved_dollars = milliunits_to_dollars(total_saved)
    if total_saved_dollars >= 2000:
        scores["Savings Contributions"] = 25
    elif total_saved_dollars >= 1500:
        scores["Savings Contributions"] = 22
    elif total_saved_dollars >= 1000:
        scores["Savings Contributions"] = 18
    elif total_saved_dollars >= 500:
        scores["Savings Contributions"] = 12
    elif total_saved_dollars > 0:
        scores["Savings Contributions"] = 6
    else:
        scores["Savings Contributions"] = 0

    # Transaction Hygiene (20 pts)
    hygiene = 20
    uncategorized_count = metrics.get("uncategorized_count", 0)
    missing_memo_count = metrics.get("missing_memo_count", 0)
    hygiene -= uncategorized_count * 3
    hygiene -= missing_memo_count * 2
    scores["Transaction Hygiene"] = max(0, hygiene)

    total = sum(scores.values())
    if total >= 90:
        letter = "A"
    elif total >= 80:
        letter = "B"
    elif total >= 70:
        letter = "C"
    elif total >= 60:
        letter = "D"
    else:
        letter = "F"

    return {"letter": letter, "total": total, "scores": scores}


def generate_executive_summary(metrics, grade):
    """Generate a curmudgeonly narrative paragraph summarizing the month."""
    lines = []
    letter = grade["letter"]
    total_spent_d = milliunits_to_dollars(metrics["total_spent"])
    total_budgeted_d = milliunits_to_dollars(metrics["total_budgeted"])
    income_d = milliunits_to_dollars(metrics["income"])
    eo_spent = metrics["eating_out_spent"]
    eo_cap = metrics["eating_out_cap"]
    total_saved_d = milliunits_to_dollars(metrics["total_saved"])

    if letter == "A":
        lines.append(
            f"A solid month. You earned ${income_d:,.0f}, spent ${total_spent_d:,.0f} against "
            f"${total_budgeted_d:,.0f} budgeted, and put away ${total_saved_d:,.0f} in savings. "
            f"Don't get smug—consistency is what matters, and one good month doesn't make a trend."
        )
    elif letter == "B":
        lines.append(
            f"Decent, not great. ${total_spent_d:,.0f} spent against ${total_budgeted_d:,.0f} budgeted, "
            f"with ${total_saved_d:,.0f} saved. There's room for improvement, but you're not in trouble."
        )
    elif letter == "C":
        lines.append(
            f"Mediocre. You spent ${total_spent_d:,.0f} on a ${total_budgeted_d:,.0f} budget and "
            f"only managed ${total_saved_d:,.0f} in savings. This is the financial equivalent of a C average—"
            f"you're passing, but nobody's impressed."
        )
    elif letter == "D":
        lines.append(
            f"Rough month. ${total_spent_d:,.0f} spent against ${total_budgeted_d:,.0f} budgeted, "
            f"savings at just ${total_saved_d:,.0f}. You're one bad month away from falling behind."
        )
    else:
        lines.append(
            f"This was a bad month and you know it. ${total_spent_d:,.0f} blown against "
            f"${total_budgeted_d:,.0f} budgeted, ${total_saved_d:,.0f} saved. "
            f"Time for some hard conversations with yourself about priorities."
        )

    if eo_spent > eo_cap:
        lines.append(
            f"Eating out hit ${eo_spent:,.0f}—that's ${eo_spent - eo_cap:,.0f} over the ${eo_cap:.0f} cap. "
            f"Learn to cook."
        )
    elif eo_spent > eo_cap * 0.9:
        lines.append(
            f"Eating out came in at ${eo_spent:,.0f}, dangerously close to the ${eo_cap:.0f} cap. Careful.")

    if metrics["uncategorized_count"] > 0:
        lines.append(
            f"{metrics['uncategorized_count']} uncategorized transactions—sloppy bookkeeping.")

    if metrics["missing_memo_count"] > 0:
        lines.append(
            f"{metrics['missing_memo_count']} large transactions without memos. "
            f"Future you will have no idea what these were for.")

    return " ".join(lines)


def generate_retrospective(year=None, month=None):
    """Main orchestrator for the monthly retrospective report."""
    today = date.today()

    # Default to previous month
    if year is None and month is None:
        prev = today - relativedelta(months=1)
        year, month = prev.year, prev.month
    else:
        if year is None:
            year = today.year
        if month is None:
            month = today.month

    # Validate month is not in the future
    target_first = date(year, month, 1)
    current_first = date(today.year, today.month, 1)
    if target_first >= current_first:
        print(f"Error: {year}-{month:02d} is the current or a future month. "
              f"Retrospectives are for completed months only.")
        return None

    month_str = get_month_string(year, month)
    month_label = f"{year}-{month:02d}"
    print(f"Generating retrospective for {month_label}...")

    client = YNABClient()

    # Fetch month data
    month_data = client.get_month(month_str)
    categories = month_data["categories"]

    # Fetch transactions for the month
    start_date = f"{year:04d}-{month:02d}-01"
    next_month = date(year, month, 1) + relativedelta(months=1)
    # Get transactions that cover this month
    transactions = client.get_transactions(since_date=start_date)
    month_txns = [
        t for t in transactions
        if not t["deleted"] and t["date"][:7] == f"{year:04d}-{month:02d}"
    ]

    # Build each section
    income = calculate_income(month_txns)
    spending = build_spending_overview(categories)
    eating_out = build_eating_out_section(client, month_str, client.config)
    savings = build_savings_section(categories)
    notable = build_notable_transactions(month_txns, client.config)

    # Net worth reconstruction
    print("Reconstructing net worth (this may take a moment)...")
    nw_current = reconstruct_net_worth(client, year, month)
    prev_month = date(year, month, 1) - relativedelta(months=1)
    nw_previous = reconstruct_net_worth(client, prev_month.year, prev_month.month)
    nw_delta = nw_current["net_worth"] - nw_previous["net_worth"]

    # Calculate totals for grading
    total_budgeted = 0
    total_spent = 0
    for group_data in spending.values():
        total_budgeted += group_data["budgeted"]
        total_spent += group_data["spent"]

    total_saved = sum(s["budgeted"] for s in savings)

    metrics = {
        "income": income,
        "total_spent": total_spent,
        "total_budgeted": total_budgeted,
        "eating_out_spent": eating_out["spent"],
        "eating_out_cap": eating_out["cap"],
        "total_saved": total_saved,
        "uncategorized_count": len(notable["uncategorized"]),
        "missing_memo_count": len(notable["missing_memo"]),
    }

    grade = calculate_grade(metrics)
    exec_summary = generate_executive_summary(metrics, grade)

    # Build prose analyses
    cash_flow_analysis = build_cash_flow_analysis(income, total_spent, total_saved)
    spending_analysis = build_spending_analysis(spending, total_spent, total_budgeted)
    eating_out_analysis = build_eating_out_analysis(eating_out)
    savings_analysis = build_savings_analysis(savings, total_saved, income)
    net_worth_analysis = build_net_worth_analysis(nw_current, nw_previous, nw_delta, income)
    grade_analysis = build_grade_analysis(grade, metrics)

    # Assemble markdown report
    lines = [
        f"# Monthly Retrospective - {month_label}",
        f"",
        f"Generated: {today}",
        f"",
        f"## Executive Summary",
        f"",
        f"{exec_summary}",
        f"",
    ]

    # Grade section
    lines.extend([
        f"## Month Grade: {grade['letter']} ({grade['total']}/100)",
        f"",
        f"| Dimension | Score | Max |",
        f"|-----------|-------|-----|",
    ])
    for dimension, score in grade["scores"].items():
        max_pts = {"Budget Adherence": 30, "Eating Out Discipline": 25,
                   "Savings Contributions": 25, "Transaction Hygiene": 20}[dimension]
        lines.append(f"| {dimension} | {score} | {max_pts} |")
    lines.extend([
        f"| **Total** | **{grade['total']}** | **100** |",
        f"",
        f"{grade_analysis}",
        f"",
    ])

    # Cash flow section
    lines.extend([
        f"## Cash Flow",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Income | **{format_currency(income)}** |",
        f"| Total Spending | {format_currency(total_spent)} |",
        f"| Savings Earmarked | {format_currency(total_saved)} |",
    ])
    if income > 0:
        lines.append(
            f"| Savings Rate | {milliunits_to_dollars(total_saved) / milliunits_to_dollars(income) * 100:.0f}% |"
        )
    lines.extend([
        f"",
        f"{cash_flow_analysis}",
        f"",
    ])

    # Spending overview
    lines.extend([
        f"## Spending Overview",
        f"",
        f"| Category Group | Spent | Budgeted | % Used |",
        f"|----------------|-------|----------|--------|",
    ])
    for group_name in sorted(spending.keys()):
        gd = spending[group_name]
        pct = (gd["spent"] / gd["budgeted"] * 100) if gd["budgeted"] > 0 else 0
        status = f"{pct:.0f}%" if gd["budgeted"] > 0 else "no budget"
        lines.append(
            f"| {group_name} | {format_currency(gd['spent'])} | "
            f"{format_currency(gd['budgeted'])} | {status} |"
        )
    lines.extend([
        f"| **Total** | **{format_currency(total_spent)}** | "
        f"**{format_currency(total_budgeted)}** | "
        f"**{(total_spent / total_budgeted * 100) if total_budgeted > 0 else 0:.0f}%** |",
        f"",
        f"{spending_analysis}",
        f"",
    ])

    # Top categories by spending
    all_cats = []
    for gd in spending.values():
        all_cats.extend(gd["categories"])
    all_cats.sort(key=lambda x: x["spent"], reverse=True)
    top_cats = all_cats[:10]

    if top_cats:
        lines.extend([
            f"### Top Categories",
            f"",
            f"| Category | Spent | Budgeted |",
            f"|----------|-------|----------|",
        ])
        for cat in top_cats:
            lines.append(
                f"| {cat['name']} | {format_currency(cat['spent'])} | "
                f"{format_currency(cat['budgeted'])} |"
            )
        lines.append("")

    # Eating out section
    lines.extend([
        f"## Eating Out Watch",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Spent | **${eating_out['spent']:,.2f}** |",
        f"| Hard Cap | ${eating_out['cap']:.2f} |",
        f"| Remaining | ${eating_out['remaining']:,.2f} |",
        f"| % of Cap | {eating_out['pct_of_cap']:.0f}% |",
        f"| Status | {'OVER' if eating_out['over'] else 'Under'} |",
        f"",
        f"{eating_out_analysis}",
        f"",
    ])

    # Savings section
    lines.extend([
        f"## Savings & Goals",
        f"",
    ])
    if savings:
        lines.extend([
            f"| Fund | Saved (Budgeted) | Withdrawn (Activity) |",
            f"|------|------------------|----------------------|",
        ])
        total_withdrawn = 0
        for s in savings:
            saved_str = format_currency(s["budgeted"])
            withdrawn = -s["activity"]
            total_withdrawn += withdrawn
            withdrawn_str = format_currency(withdrawn) if withdrawn > 0 else "$0.00"
            lines.append(f"| {s['name']} | {saved_str} | {withdrawn_str} |")
        lines.extend([
            f"| **Total** | **{format_currency(total_saved)}** | "
            f"**{format_currency(total_withdrawn)}** |",
            f"",
        ])
    else:
        lines.extend(["No savings/fund categories found.", ""])
    lines.extend([
        f"{savings_analysis}",
        f"",
    ])

    # Net worth section
    lines.extend([
        f"## Net Worth Snapshot",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Assets | {format_currency(nw_current['assets'])} |",
        f"| Liabilities | {format_currency(nw_current['liabilities'])} |",
        f"| **Net Worth** | **{format_currency(nw_current['net_worth'])}** |",
        f"| Month-over-Month Change | {'+' if nw_delta >= 0 else ''}{format_currency(nw_delta)} |",
        f"",
        f"{net_worth_analysis}",
        f"",
    ])

    # Notable transactions
    lines.extend([
        f"## Notable Transactions",
        f"",
    ])

    if notable["large"]:
        lines.extend([
            f"### Large Transactions (>${client.config['review_settings']['flag_large_transactions_above']})",
            f"",
            f"| Date | Payee | Amount | Category |",
            f"|------|-------|--------|----------|",
        ])
        for txn in notable["large"]:
            lines.append(
                f"| {txn['date']} | {txn['payee_name']} | "
                f"{format_currency(txn['amount'])} | {txn['category_name'] or 'N/A'} |"
            )
        lines.append("")

    issues = []
    if notable["uncategorized"]:
        issues.append(f"{len(notable['uncategorized'])} uncategorized transactions")
    if notable["missing_memo"]:
        issues.append(f"{len(notable['missing_memo'])} transactions missing memos (>${client.config['review_settings']['require_memo_for_transactions_above']})")

    if issues:
        lines.extend([
            f"### Issues",
            f"",
        ])
        for issue in issues:
            lines.append(f"- {issue}")
        lines.append("")
    elif not notable["large"]:
        lines.extend(["No notable transactions or issues this month.", ""])

    # Footer
    lines.extend([
        f"---",
        f"",
        f"*API calls: {client.cache_stats['misses']} fresh, {client.cache_stats['hits']} cached*",
    ])

    report_content = "\n".join(lines)

    md_path, html_path = save_report("monthly-retrospective", report_content, month_label)

    print(report_content)
    print(f"\n---\nReports saved to:\n  {md_path}\n  {html_path}")

    return report_content


def main():
    parser = argparse.ArgumentParser(description="Monthly financial retrospective with letter grade")
    parser.add_argument("--year", "-y", type=int, help="Year (default: previous month's year)")
    parser.add_argument("--month", "-m", type=int, help="Month (default: previous month)")
    args = parser.parse_args()

    generate_retrospective(args.year, args.month)


if __name__ == "__main__":
    main()
