# Intuition Collector and Public Operations

Canonical GitHub-hosted execution repository for Jarvis Intuition.

## Active topology

`Public GitHub Actions (ubuntu-latest) -> BetsAPI / Telegram / private state repository`

The repository contains collection code and public workflow definitions. Betting methodology, decisions, reports, settlements, publication markers and historical data remain private in `Dzammbo/jarvis-intuition`.

## Collection workflows

- `Collect Universe`
- `Collect Tennis Singles Event View`
- `L1 Tennis Singles Market Scan`
- `Build Tennis Singles Research Packet` - lossless handoff of every technically eligible single, including rows waiting for price
- `Build Baseline Tennis Player Dossiers` - manual-only baseline builder. It requires the matching Universe and Event View runs, collects the official complete WTA Singles Numeric PDF and every page of the TennisExplorer ATP ranking. Before requesting a static player profile, it checks the persistent canonical profile registry by provider player ID and canonical name; only new, unresolved or conflicting players are fetched. Static profiles contribute date of birth, age at cutoff, nationality, handedness, height, weight and sex with field-level provenance. The builder also reuses unchanged player histories by stable source fingerprint and stores match-specific Event View context separately. It does not claim full multi-source enrichment. The same manual run now builds a separate non-scoring pre-deep-research enrichment packet for every match. It aligns surface form, opponent quality, serve/return availability, workload, known duration and qualification context, travel endpoints, comparable-level history, age/experience/sample coverage, health gaps and current sourced observations. Unchanged event packets are reused by source fingerprint; missing optional data stays explicit and never excludes a match.
- `Sync BetsAPI League Registry` - legacy provider-name and audit support only; it does not gate active tennis eligibility

Football, baseball, ice hockey and basketball are excluded before daily provider collection. The active collector runs the two UTC-day tennis feeds needed for the rolling 24-hour window. Historical artifacts remain available only for settlement and analytics.

The provider catalog and old tier overlay remain for historical provenance and
diagnostics. CORE/SECONDARY/EXCLUDE is not used to admit, defer or reject an
active tennis singles event.

## Operational workflows

- `Check Final Card Settlement`
- `Daily Settlement`
- `Rerender Results`
- `Native Telegram Publish`
- `Capture Bet365 Closing Line` - every five minutes, diagnostic only; tracks
  the exact Bet365 target for each BET and substantive PASS without delaying
  selection or publication
- `Validate Public Operations`

Operational workflows run on public GitHub-hosted runners, check out the private state repository with a restricted token, execute its canonical scripts, and write generated state back to the private repository.

## Required Actions secrets

- `BETS_API`
- `JARVIS_PRIVATE_REPO_TOKEN` - fine-grained token scoped only to `Dzammbo/jarvis-intuition`, repository Contents read/write
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

## Trigger model

Selection and publication stages remain explicit. The only clock-scheduled
workflow is the non-blocking Bet365 closing-line recorder. Other collection and
operational workflows can be started manually. Canonical trigger files are also
supported for plugin-driven execution:

- `triggers/run-universe.txt`
- `triggers/run-league-registry.txt`
- `triggers/run-final-card-check.txt`
- `triggers/run-settlement-check.txt`
- `triggers/run-rerender-results.txt`
- `triggers/run-telegram-publish.txt`
- `triggers/run-validation.txt`
- `triggers/run-player-dossiers.txt` - four operative lines: Universe run ID, matching Event View run ID, Moscow card date, optional diagnostic match limit

Vercel, Railway, Selectel and self-hosted runners are not part of this architecture.
