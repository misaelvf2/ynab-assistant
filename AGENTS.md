# YNAB Financial Assistant

This repository can be driven by either Claude Code or Pi Coding Agent.

## Primary Project Guidance

Detailed budgeting behavior lives in these skill docs:

- `.claude/skills/ynab-api/SKILL.md` — YNAB API usage, SDK patterns, caching, data formats
- `.claude/skills/personal-budget/SKILL.md` — onboarding, budget rules, script generation, request routing, dashboard conventions

Agents working in this repo should read those files when the task touches budgeting behavior, onboarding, reports, dashboards, or YNAB API usage.

## Pi Coding Agent Notes

This repo includes `.pi/settings.json` so Pi can discover the project skill docs in `.claude/skills/`.

In Pi:
- use this `AGENTS.md` as the primary workspace context file
- load the relevant skill doc before implementing budget-specific behavior
- use the existing scripts and dashboard endpoints rather than reinventing logic

## Shared Conventions

- Run scripts with: `uv run python scripts/<script>.py`
- Start dashboard with: `uv run uvicorn dashboard.app:app --reload --port 8000`
- Config lives in `config.json`
- YNAB token lives in `.env` as `YNAB_PAT`
- Generated reports are written to `reports/`
- User-specific scripts live in `user_scripts/`
- Dashboard plugins live in `dashboard/plugins/`

## Agent Role

The scripts and dashboard provide the data and mechanics. The agent is responsible for:
- routing requests to the right script or endpoint
- reading project docs before changing behavior
- interpreting output using the configured budget rules and tone guidance
- keeping changes config-driven and reusable where possible
