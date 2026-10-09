# Holistic deep-research decision contract

Effective for decisions frozen after `2026-10-09T11:34:00Z`.

## Decision order

1. Complete player-specific deep research for both players and the matchup.
2. Weigh concrete supporting facts, counterevidence, uncertainty and unresolved gaps.
3. Freeze the exact selected side and the research decision: `BET`, `PASS` or `NO_DATA`.
4. Only after the freeze, collect the Bet365 Match Winner price when available.
5. Store price, implied probability and any EV-like calculation only as post-decision diagnostics for later calibration.

## Meaning of statuses

- `BET`: the holistic sporting evidence supports the selected side strongly enough for inclusion.
- `PASS`: an exact price-blind lean is preserved for outcome tracking, but the holistic evidence is not strong or reliable enough for inclusion.
- `NO_DATA`: sporting evidence is insufficient even to record a defensible lean. Missing bookmaker price is not `NO_DATA`.

## Forbidden decision logic

- `EV > 0 -> BET`, `EV <= 0 -> PASS`.
- Any odds, price, implied-probability or price-threshold rule that changes `BET` to `PASS` or the reverse.
- Fixed probability buckets used as a substitute for player-specific research.
- A list of searches or generic template text presented as deep research when the retrieved facts did not materially enter the judgment.
- Changing the selected side after price reveal.

## Required audit fields

Every new final decision must declare `decision_method_contract` as
`2026-10-09-holistic-deep-research-v1`, set
`decision_frozen_before_price` to `true`, and include a
`deep_research_judgment` object with the exact selected side, matching research
decision, concrete supporting facts, counterevidence, uncertainties, explicit
reasons for `PASS` where applicable, evidence weighing and source references.

The Bet365 price remains useful. It is recorded after the decision so later
analysis can learn which price ranges perform better or worse without allowing
an uncalibrated EV estimate to decide the current card.
