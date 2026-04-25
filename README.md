# YNAB Financial Assistant

A personal finance assistant for [YNAB](https://www.ynab.com/) (You Need A Budget) that can be driven by either [Claude Code](https://docs.anthropic.com/en/docs/claude-code) or [Pi Coding Agent](https://github.com/mariozechner/pi-coding-agent). Instead of running scripts manually, you talk to your coding agent — ask about your spending, net worth, or transactions, and it runs the right tools, interprets the data, and responds in your preferred tone.

The project keeps its agent-facing budgeting instructions in Claude Code-style skill specs under `.claude/skills/`, plus a top-level `AGENTS.md` for cross-agent workspace guidance and a `CLAUDE.md` compatibility file.

- `.claude/skills/ynab-api/SKILL.md` — YNAB SDK wrapper, caching, data formats
- `.claude/skills/personal-budget/SKILL.md` — onboarding, script generation, budget rules, request routing

## Agent Compatibility

This repo is agent-friendly rather than tied to a single coding assistant:

- **Claude Code** can use the `.claude/skills/` skill specs directly.
- **Pi Coding Agent** can use `AGENTS.md` as workspace instructions and, via `.pi/settings.json`, discover the project skill docs in `.claude/skills/`.
- The Python scripts, dashboard, configuration, and reports are agent-agnostic — the agent mainly handles routing, tool use, and commentary.

If you are using a different agent, you can still run the same scripts manually from the command line.

## How It Works

1. **You talk to your agent** — "What's my net worth?", "How's my spending pace?", "Review my transactions"
2. **The agent routes to the right script**, runs it, and reads the output
3. **The agent interprets the results** using your personalized tone and budget rules, then responds with commentary

Scripts produce structured data. The agent adds the personality and context. This separation keeps scripts reusable and lets the workflow adapt across agents.

## Setup

1. Clone the repo
2. Install [uv](https://docs.astral.sh/uv/) if you don't have it:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```
3. Install dependencies:
   ```bash
   uv sync
   ```
4. Add your YNAB Personal Access Token to a `.env` file:
   ```
   YNAB_PAT=your_token_here
   ```
   Get a token at https://app.ynab.com/settings/developer.
5. **Start a Claude Code or Pi Coding Agent session and let it onboard you.** Your agent will:
   - Connect to your YNAB budget
   - Show your category structure
   - Ask about spending caps, savings goals, net worth milestones, and preferred tone
   - Generate `config.json`, `tone-guide.md`, user-specific scripts, and dashboard plugins

See the [personal-budget skill spec](.claude/skills/personal-budget/SKILL.md) for the full onboarding flow and script-generation rules.

## Using with Pi Coding Agent

This repo includes Pi-native project wiring:

- `AGENTS.md` provides workspace guidance for Pi.
- `.pi/settings.json` points Pi at `../.claude/skills`, so Pi can discover the existing project skill docs.
- The same scripts, dashboard, config files, and reports are shared across Pi and Claude Code.

In practice:

- Open the repo in Pi.
- Let Pi load `AGENTS.md` automatically.
- Ask Pi to use the relevant skill doc when it needs onboarding rules, YNAB API guidance, or dashboard/script-generation patterns.
- Run the same commands described elsewhere in this README.

Pi and Claude Code still have different runtimes, but they now share the same project instructions and workflow docs more directly.

## Running Scripts Yourself

Once onboarded, you're free to run any script directly from the command line.

**Generic scripts** (work for any YNAB budget):

| Script | Purpose | Key Flags |
|--------|---------|-----------|
| `scripts/spending_summary.py` | Monthly spending by category | `-y YEAR`, `-m MONTH` |
| `scripts/net_worth.py` | Current net worth snapshot | `--save`, `--compare DATE`, `--list-snapshots` |
| `scripts/net_worth_history.py` | Historical net worth trends | `--months N` |
| `scripts/review_transactions.py` | Flag transaction issues | `--days N`, `--memo-threshold N` |
| `scripts/spending_velocity.py` | Spending pace & projections | `--threshold N`, `--alerts-only` |

```bash
uv run python scripts/spending_summary.py
uv run python scripts/net_worth.py --save
```

**User-specific scripts** are generated during onboarding into `user_scripts/` — these are tailored to your budget (e.g. category trackers with your spending caps, monthly retrospectives with your grading dimensions). See the personal-budget skill spec for the patterns used to generate them.

## Web Dashboard

```bash
uv run uvicorn dashboard.app:app --reload --port 8000
# Open http://localhost:8000
```

The dashboard serves generic endpoints (`/api/summary`, `/api/net-worth`, etc.) plus user-specific plugin endpoints generated during onboarding. Plugins live in `dashboard/plugins/` and are auto-discovered on startup.

## Reports

Scripts save Markdown and HTML reports to `reports/`, overwritten when regenerated for the same period. HTML reports include styled tables and interactive Chart.js graphs where applicable.

## Configuration

- `config.json` — all settings: budget connection, spending caps, milestones, grading, review thresholds (generated during onboarding from `config.template.json`, gitignored)
- `tone-guide.md` — personality, interpretation rules, commentary guidance (generated during onboarding from `tone-guide.example.md`, gitignored)
- `.env` — YNAB API token (gitignored)

## Caching

API responses are cached in `cache/api/` (default 5-minute TTL, 24 hours for historical data). Net worth snapshots are stored in `cache/net_worth_snapshots.json`.

## License

[MIT](LICENSE)
