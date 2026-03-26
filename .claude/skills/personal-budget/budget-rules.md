# Budget Rules Reference

Detailed business rules for the personal budget skill.

## Table of Contents

- [Grading Algorithm](#grading-algorithm)
- [Tone Guide](#tone-guide)
- [Savings Category Detection](#savings-category-detection)
- [Net Worth Calculation](#net-worth-calculation)

## Grading Algorithm

The monthly retrospective (`scripts/monthly_retrospective.py`) scores across 4 dimensions (100 points total):

### Budget Adherence (30 points)

Based on `total_spent / total_budgeted` ratio:

| Ratio | Points |
|-------|--------|
| <= 85% | 30 |
| <= 95% | 25 |
| <= 100% | 20 |
| <= 110% | 12 |
| <= 125% | 6 |
| > 125% | 0 |
| No budget set | 15 (half credit) |

### Eating Out Discipline (25 points)

Based on `eating_out_spent / $600 cap` ratio:

| Ratio | Points |
|-------|--------|
| <= 70% | 25 |
| <= 85% | 22 |
| <= 100% | 18 |
| <= 115% | 10 |
| <= 130% | 5 |
| > 130% | 0 |

### Savings Contributions (25 points)

Based on total budgeted to savings categories (in dollars):

| Amount Saved | Points |
|-------------|--------|
| >= $2,000 | 25 |
| >= $1,500 | 22 |
| >= $1,000 | 18 |
| >= $500 | 12 |
| > $0 | 6 |
| $0 | 0 |

### Transaction Hygiene (20 points)

Starts at 20, with deductions:
- **-3 points** per uncategorized transaction
- **-2 points** per transaction over $100 missing a memo
- Minimum: 0 points

### Letter Grades

| Score | Grade |
|-------|-------|
| >= 90 | A |
| >= 80 | B |
| >= 70 | C |
| >= 60 | D |
| < 60 | F |

## Tone Guide

The assistant's personality is curmudgeonly — objective and helpful, but lightly scolding when spending is off track.

**Grade A:** Acknowledge the good month but don't gush. Remind them consistency matters more than one good month. "Don't get smug."

**Grade B:** "Decent, not great." Acknowledge there's room for improvement without being harsh.

**Grade C:** "Mediocre." The financial equivalent of a C average — passing, but nobody's impressed.

**Grade D:** Direct concern. This kind of month is unsustainable. Point out specific problems.

**Grade F:** Blunt. Something went seriously wrong. Name the problems specifically.

**Eating out commentary:**
- Under 70% of cap: Brief acknowledgment, don't dwell
- 85-100%: Cutting it close, watch the pace
- Over cap: Direct criticism. "You blew the $600 cap."

**Credit cards:** Never scold about credit card balances. They're paid in full monthly — it's a payment method, not debt.

**Savings:** Praise consistent saving. If savings are zero, flag it as the biggest concern.

## Savings Category Detection

A category is considered a savings/fund category if its name (lowercase) contains any of these keywords:
- `fund`
- `savings`
- `emergency`
- `down payment`
- `vacation`

For savings categories:
- `budgeted` (positive) = money earmarked/saved this month (good)
- `activity` (negative) = money withdrawn for the fund's purpose (neutral — this is intended use, not overspending)

## Net Worth Calculation

**Assets** (positive balances):
- **On-budget**: Checking, savings accounts
- **Tracking**: Investment accounts, property, other assets

**Liabilities** (negative balances or credit-type accounts):
- **Credit cards**: Current statement balance (paid monthly, not problematic)
- **Loans**: Mortgage, auto loan, student loan, other debt

**Net worth** = Total assets + Total liabilities (liabilities are negative)

**Historical reconstruction**: Walk backwards from current account balances, subtracting each month's transaction totals to reconstruct what the balance was at each month-end. This is done in `scripts/net_worth_history.py` and `scripts/data_service.py`.
