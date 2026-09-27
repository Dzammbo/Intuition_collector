# Intuition Collector and Public Operations

Canonical GitHub-hosted execution repository for Jarvis Intuition.

## Active topology

`Public GitHub Actions (ubuntu-latest) -> BetsAPI / Telegram / private state repository`

The repository contains collection code and public workflow definitions. Betting methodology, decisions, reports, settlements, publication markers and historical data remain private in `Dzammbo/jarvis-intuition`.

## Collection workflows

- `Collect Universe`
- `Collect CORE Event View`
- `L1 Broad Signal Market Scan`

## Operational workflows

- `Check Final Card Settlement`
- `Daily Settlement`
- `Rerender Results`
- `Native Telegram Publish`
- `Validate Public Operations`

Operational workflows run on public GitHub-hosted runners, check out the private state repository with a restricted token, execute its canonical scripts, and write generated state back to the private repository.

## Required Actions secrets

- `BETS_API`
- `JARVIS_PRIVATE_REPO_TOKEN` - fine-grained token scoped only to `Dzammbo/jarvis-intuition`, repository Contents read/write
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Trigger model

All production stages are explicit and have no clock schedules. Collection and operational workflows can be started manually. Canonical trigger files are also supported for plugin-driven execution:

- `triggers/run-universe.txt`
- `triggers/run-final-card-check.txt`
- `triggers/run-settlement-check.txt`
- `triggers/run-rerender-results.txt`
- `triggers/run-telegram-publish.txt`
- `triggers/run-validation.txt`

Vercel, Railway, Selectel and self-hosted runners are not part of this architecture.
