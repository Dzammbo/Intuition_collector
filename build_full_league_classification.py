#!/usr/bin/env python3
"""Freeze an exact tier for every league in the provider registry.

Name and metadata rules are used only while building the versioned registry.
Daily classification continues to match exact ``sport_id + league_id`` keys.
Existing canonical decisions always win.
"""

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path


CATALOG = Path("config/league_registry_v1/catalog.json")
OUTPUT = Path(os.environ.get(
    "CLASSIFICATION_OUTPUT",
    "config/league_allowset_v1/complete_registry_classification.json",
))
STATUS = os.environ.get("CLASSIFICATION_STATUS", "CANONICAL_COPY")

NON_SENIOR = re.compile(
    r"\b(esoccer|ebasketball|eicehockey|virtual|simulated|friendly|friendlies|"
    r"school|college|university|academy|amateur|reserve|reserves|development|"
    r"junior|juniors|youth|u[- ]?\d{1,2}|under[- ]?\d{1,2}|boys?|girls?|"
    r"3x3|padel|beach|futsal|ncaa[bh]?|matches|hypothetical|test|futures|"
    r"look ahead|summer league)\b|premier league 2|primavera|juniorallsvenskan|"
    r"kings? (league|world cup)",
    re.I,
)
WOMEN = re.compile(
    r"\b(women|womens|woman|feminil|femenil|feminina|feminine|femenina|"
    r"damallsvenskan|toppserien|wnba|wncaa|wnbl|waba|awbl|zbl|lfb|dbbl|"
    r"wbl|w league)\b|\(w\)",
    re.I,
)
CUP_OR_QUALIFYING = re.compile(
    r"\b(cup|trophy|super ?cup|pokal|coppa|copa|coupe|taça|shield|"
    r"all[- ]?star|qualification|qualifying|play[- ]?offs?)\b",
    re.I,
)


def match(pattern, text):
    return bool(re.search(pattern, text, re.I))


def classify_unknown(row):
    name = row["league_name"]
    sport = row["sport"]

    if sport == "tennis":
        if NON_SENIOR.search(name) or match(r"\butr\b|wheelchair|table tennis", name):
            return "EXCLUDE", "NON_PRO_OR_NON_TENNIS_FORMAT"
        if match(
            r"^(atp|wta|challenger|itf\b|m\d{2,3}\b|w\d{2,3}\b)|"
            r"\b(australian open|french open|roland garros|wimbledon|us open|olympics)\b",
            name,
        ):
            return "CORE", "PROFESSIONAL_TENNIS_TOUR"
        if match(
            r"davis cup|billie jean|fed cup|laver cup|hopman cup|united cup|"
            r"world tennis league|exhibition|battle of",
            name,
        ):
            return "SECONDARY", "TEAM_OR_EXHIBITION_TENNIS"
        return "EXCLUDE", "OUTSIDE_POSITIVE_TENNIS_SCOPE"

    if sport == "soccer":
        if NON_SENIOR.search(name):
            return "EXCLUDE", "NON_SENIOR_OR_NON_STANDARD"
        if match(
            r"\b(division 4|division 5|4th|5th|4\. liga|5\. liga|"
            r"serie d|serie e|oberliga|landesliga|tercera|regional amateur|"
            r"4 deild|conference league 2)\b",
            name,
        ):
            return "EXCLUDE", "LOW_TIER"
        if WOMEN.search(name):
            return "SECONDARY", "WOMENS_COMPETITION"
        if match(
            r"uefa champions league|uefa europa league|conference league|"
            r"copa libertadores|copa sudamericana|world cup|afc asian cup|"
            r"africa cup of nations|nations league|major league soccer|\bmls\b",
            name,
        ):
            return "CORE", "ELITE_OR_MAJOR_INTERNATIONAL"
        if CUP_OR_QUALIFYING.search(name):
            return "SECONDARY", "CUP_OR_QUALIFYING"
        if match(
            r"\b(division 3|3rd|3\. liga|serie c|liga 3|league one|"
            r"national league|regionalliga|third league|ii liga|"
            r"segunda division rfef)\b",
            name,
        ):
            return "SECONDARY", "THIRD_TIER_OR_REGIONAL_PRO"
        if row["has_toplist"]:
            return "CORE", "PROVIDER_HIGH_RESEARCHABILITY"
        if match(
            r"\b(premier league|premiership|primera division|primeira liga|"
            r"serie a|serie b|liga 1|liga i|super ?liga|super league|"
            r"bundesliga|ligue 1|ligue 2|eredivisie|championship|division 1|"
            r"division 2|first division|second division|j[- ]?league|"
            r"k[- ]?league|pro league|professional league|a league|"
            r"allsvenskan|eliteserien|veikkausliiga|ekstraklasa)\b",
            name,
        ):
            return "CORE", "RECOGNIZED_SENIOR_PRO_LEAGUE"
        if row["has_league_table"]:
            return "SECONDARY", "PROVIDER_RESEARCHABLE_SECONDARY"
        return "EXCLUDE", "OUTSIDE_POSITIVE_SOCCER_SCOPE"

    if sport == "basketball":
        if NON_SENIOR.search(name):
            return "EXCLUDE", "NON_SENIOR_OR_NON_STANDARD"
        if WOMEN.search(name):
            return "SECONDARY", "WOMENS_COMPETITION"
        if CUP_OR_QUALIFYING.search(name) or match(r"pre[- ]?season", name):
            return "SECONDARY", "CUP_OR_QUALIFYING"
        if match(
            r"\b(nba|euroleague|euro ?cup|basketball champions league|"
            r"fiba world cup|fiba europe cup|nbl|cba|kbl|pba|liga acb|"
            r"liga nacional|vtb|adriatic league|b league|lnbp)\b",
            name,
        ):
            return "CORE", "RECOGNIZED_SENIOR_PRO_LEAGUE"
        if row["has_league_table"]:
            return "SECONDARY", "PROVIDER_RESEARCHABLE_SECONDARY"
        return "EXCLUDE", "OUTSIDE_POSITIVE_BASKETBALL_SCOPE"

    if sport == "ice_hockey":
        if NON_SENIOR.search(name) or match(r"pre[- ]?season|\bmhl\b|\bohl\b|\bwhl\b", name):
            return "EXCLUDE", "NON_SENIOR_OR_DEVELOPMENTAL"
        if WOMEN.search(name):
            return "SECONDARY", "WOMENS_COMPETITION"
        if CUP_OR_QUALIFYING.search(name):
            return "SECONDARY", "CUP_OR_QUALIFYING"
        if match(
            r"\b(nhl|ahl|khl|vhl|shl|del|liiga|extraliga|hockeyallsvenskan|"
            r"mestis|echl|spengler cup|champions hockey league|"
            r"iihf world championship)\b",
            name,
        ) or row["has_toplist"]:
            return "CORE", "RECOGNIZED_SENIOR_PRO_LEAGUE"
        if row["has_league_table"]:
            return "SECONDARY", "PROVIDER_RESEARCHABLE_SECONDARY"
        return "EXCLUDE", "OUTSIDE_POSITIVE_HOCKEY_SCOPE"

    if sport == "baseball":
        if NON_SENIOR.search(name):
            return "EXCLUDE", "NON_SENIOR_OR_DEVELOPMENTAL"
        if match(
            r"\b(mlb|npb|kbo|cpbl|lmb|liga del pacifico|lidom|serie nacional|"
            r"world baseball classic|olympics|asian games|premier 12|"
            r"serie del caribe|australian baseball league|abl|lbprc|lbpn)\b",
            name,
        ):
            return "CORE", "RECOGNIZED_PRO_OR_MAJOR_INTERNATIONAL"
        if match(
            r"minor|triple a|exhibition|pre[- ]?season|all[- ]?star|"
            r"home run derby|reserve|winter league",
            name,
        ):
            return "SECONDARY", "DEFERRED_BASEBALL"
        return "EXCLUDE", "OUTSIDE_POSITIVE_BASEBALL_SCOPE"

    raise RuntimeError(f"unsupported sport: {sport}")


def main():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    output = []
    counts = Counter()
    by_sport = defaultdict(Counter)
    for row in data["leagues"]:
        if row["tier"] in {"CORE", "SECONDARY", "EXCLUDE"}:
            tier = row["tier"]
            reason = "PRESERVED_CANONICAL_DECISION"
        else:
            tier, reason = classify_unknown(row)
        counts[tier] += 1
        by_sport[row["sport"]][tier] += 1
        output.append(
            {
                "sport_id": row["sport_id"],
                "league_id": row["league_id"],
                "league_name": row["league_name"],
                "tier": tier,
                "tier_reason": reason,
            }
        )

    assert len(output) == data["leagues"].__len__()
    assert sum(counts.values()) == len(output)
    payload = {
        "schema_version": 1,
        "policy_version": "2026-09-28-complete-provider-registry-v1",
        "status": STATUS,
        "source_catalog_captured_at": data["captured_at"],
        "matching_key": ["sport_id", "league_id"],
        "runtime_rule": "Exact ID matching only; build-time rules are never applied during a daily run.",
        "precedence_rule": "All pre-existing canonical decisions are preserved.",
        "counts": dict(sorted(counts.items())),
        "counts_by_sport": {
            sport: dict(sorted(tiers.items())) for sport, tiers in sorted(by_sport.items())
        },
        "leagues": output,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"total": len(output), "counts": counts}, default=dict))


if __name__ == "__main__":
    main()
