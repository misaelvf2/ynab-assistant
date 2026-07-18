# YNAB Financial Assistant

This repository can be driven by any coding agent that can read workspace
instructions and run the project commands. Claude Code and Pi Coding Agent have
repository-specific integration, but neither owns the budgeting workflow.

## Primary Project Guidance

Detailed budgeting behavior lives in these shared skill docs:

- `.claude/skills/ynab-api/SKILL.md` — YNAB API usage, SDK patterns, caching, data formats
- `.claude/skills/personal-budget/SKILL.md` — onboarding, budget rules, script generation, request routing, dashboard conventions

Agents working in this repo should read those files when the task touches budgeting behavior, onboarding, reports, dashboards, or YNAB API usage.

The `.claude/skills/` directory name is a legacy compatibility path for Claude
Code's skill discovery. Its Markdown files are the agent-neutral project
specifications and are intentionally used by other agents too. User-specific
guidance is stored alongside the personal-budget spec at:

- `.claude/skills/personal-budget/USER_RULES.md`
- `.claude/skills/personal-budget/tone-guide.md`

## Agent Integration

This repo includes adapters for agents with their own workspace conventions:

- `AGENTS.md` is the agent-neutral entry point.
- `CLAUDE.md` provides Claude Code compatibility.
- `.pi/settings.json` lets Pi discover the shared skill docs in `.claude/skills/`.

Other agents should load this file first, then read the relevant shared skill
doc before implementing budget-specific behavior. Use the existing scripts and
dashboard endpoints rather than reinventing their logic.

## Shared Conventions

- Run scripts with: `uv run python scripts/<script>.py`
- Start dashboard with: `uv run uvicorn dashboard.app:app --reload --port 8000`
- Config lives in `config.json`
- YNAB token lives in `.env` as `YNAB_PAT`
- Generated reports are written to `reports/`
- User-specific scripts live in `user_scripts/`
- Dashboard plugins live in `dashboard/plugins/`
- Correlated/imported transaction pairs (credit-card payments, transfers, rent/card payment offsets, duplicate imported counterparts) require special care: inspect both sides before editing, convert one side to a transfer only deliberately, then re-fetch and verify whether YNAB created/matched a counterpart before deleting or approving the other side. Verify `cleared` status on every transaction in the correlated unit; if the unit is fully understood and reconciles to imported/cleared activity, set generated or linked counterparts to `cleared` when appropriate.

## Agent Role

The scripts and dashboard provide the data and mechanics. The agent is responsible for:
- routing requests to the right script or endpoint
- reading project docs before changing behavior
- interpreting output using the configured budget rules and tone guidance
- keeping changes config-driven and reusable where possible
