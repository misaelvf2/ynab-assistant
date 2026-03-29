# YNAB Financial Assistant

This workspace uses Claude Code agent skills. See:

- `.claude/skills/ynab-api/SKILL.md` — YNAB API (SDK, data formats, caching wrapper)
- `.claude/skills/personal-budget/SKILL.md` — Budget rules, scripts, personality

## Quick Reference

Run scripts: `uv run python scripts/<script>.py`
Start dashboard: `uv run uvicorn dashboard.app:app --reload --port 8000`
Config: `config.json` | Token: `.env` (YNAB_PAT)
