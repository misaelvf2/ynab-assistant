# YNAB Financial Assistant

Claude Code compatibility file.

Use `AGENTS.md` as the primary cross-agent workspace guide for this repository.

Claude-specific budgeting instructions still live in:

- `.claude/skills/ynab-api/SKILL.md` — YNAB API (SDK, data formats, caching wrapper)
- `.claude/skills/personal-budget/SKILL.md` — budget rules, onboarding, scripts, personality

## Quick Reference

Run scripts: `uv run python scripts/<script>.py`
Start dashboard: `uv run uvicorn dashboard.app:app --reload --port 8000`
Config: `config.json` | Token: `.env` (YNAB_PAT)
