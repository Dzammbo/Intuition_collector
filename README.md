# Intuition Collector

Canonical BetsAPI collection and deterministic data-preparation repository for Jarvis Intuition.

## Active topology

`GitHub Actions (ubuntu-latest) -> BetsAPI -> GitHub artifacts`

This repository contains no betting methodology and makes no BET/PASS decisions.

## Active workflows

- `Collect Universe` - complete Raw Universe collection and deterministic league classification
- `Collect CORE Event View` - Event View collection for the saved CORE lane
- `L1 Broad Signal Market Scan` - one saved L1 market snapshot for the saved CORE lane

All stages are explicit. Only `Collect Universe` also accepts the canonical trigger file `triggers/run-universe.txt`. Downstream workflows require the source run ID and Moscow date as explicit inputs.

## Required secret

- `BETS_API`

## Active implementation

- `collector.py`
- `classify_universe.py`
- `collect_event_view.py`
- `l1_market_scan.py`
- `config/league_allowset_v1/`
