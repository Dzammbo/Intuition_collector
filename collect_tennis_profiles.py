#!/usr/bin/env python3
"""Resolve roster players to TennisExplorer profiles and capture slow-changing bio fields."""

from __future__ import annotations

import argparse
import itertools
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin
from urllib.request import Request, urlopen


BASE_URL = "https://www.tennisexplorer.com"
SEARCH_URL = BASE_URL + "/list-players/?search-text-pl={}"
SOURCE_NAME = "TENNISEXPLORER_PLAYER_PROFILE"
UNKNOWN = "UNKNOWN"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ranking_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(sorted(re.findall(r"[a-z0-9]+", text.casefold())))


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hidden = 0
        self.text: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.href: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if not self.hidden and tag == "a":
            self.href = dict(attrs).get("href")
            self.link_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1
        if not self.hidden and tag == "a" and self.href:
            self.links.append((self.href, " ".join(self.link_text).strip()))
            self.href = None
            self.link_text = []

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.text.append(cleaned)
            if self.href:
                self.link_text.append(cleaned)


def parse_search_html(html: str, requested_name: str) -> tuple[str | None, str]:
    parser = VisibleTextParser()
    parser.feed(html)
    exact = []
    subset = []
    requested_tokens = set(ranking_key(requested_name).split())
    for href, label in parser.links:
        if "/player/" not in href:
            continue
        candidate_key = ranking_key(label.replace(",", " "))
        candidate_url = urljoin(BASE_URL, href.split("?", 1)[0])
        if candidate_key == ranking_key(requested_name):
            exact.append(candidate_url)
        candidate_tokens = set(candidate_key.split())
        if len(candidate_tokens) >= 2 and candidate_tokens < requested_tokens:
            subset.append(candidate_url)
    exact = sorted(set(exact))
    if len(exact) == 1:
        return exact[0], "EXACT_NORMALIZED_TOKEN_SET_NAME"
    if len(exact) > 1:
        return None, "AMBIGUOUS_EXACT_NAME_MATCH"
    subset = sorted(set(subset))
    if len(subset) == 1:
        return subset[0], "UNIQUE_MULTI_TOKEN_SUBSET_ALIAS"
    if len(subset) > 1:
        return None, "AMBIGUOUS_MULTI_TOKEN_SUBSET_ALIAS"
    return None, "NO_EXACT_OR_UNIQUE_SUBSET_NAME_MATCH"


def first(pattern: str, text: str, cast=None):
    match = re.search(pattern, text, flags=re.I)
    if not match:
        return UNKNOWN
    value = match.group(1).strip()
    return cast(value) if cast else value


def parse_profile_html(html: str) -> dict:
    parser = VisibleTextParser()
    parser.feed(html)
    text = " ".join(parser.text)
    dob_match = re.search(r"Age:\s*\d+\s*\((\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\)", text, re.I)
    dob = (
        f"{int(dob_match.group(3)):04d}-{int(dob_match.group(2)):02d}-{int(dob_match.group(1)):02d}"
        if dob_match else UNKNOWN
    )
    ranks = re.search(
        r"Current/Highest rank\s*-\s*singles:\s*(\d+|-)\.?\s*/\s*(\d+|-)", text, re.I
    )
    return {
        "date_of_birth": dob,
        "source_reported_age": first(r"Age:\s*(\d+)", text, int),
        "nationality": first(
            r"Country:\s*(.+?)(?=\s+(?:Height\s*/\s*Weight|Age|Current/Highest rank|Sex|Plays):)", text
        ),
        "handedness": first(r"Plays:\s*(right|left)", text).upper(),
        "height_cm": first(r"Height\s*/\s*Weight:\s*(\d+)\s*cm", text, int),
        "weight_kg": first(r"Height\s*/\s*Weight:\s*\d+\s*cm\s*/\s*(\d+)\s*kg", text, int),
        "sex": first(r"Sex:\s*(man|woman)", text).upper(),
        "current_singles_rank": int(ranks.group(1)) if ranks and ranks.group(1).isdigit() else UNKNOWN,
        "highest_singles_rank": int(ranks.group(2)) if ranks and ranks.group(2).isdigit() else UNKNOWN,
    }


def fetch(url: str, attempts: int = 4) -> str:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; JarvisIntuition/1.0)"})
            with urlopen(request, timeout=30) as response:
                return response.read().decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed after {attempts} attempts: {url}: {last_error}")


def resolve_profile_url(name: str) -> tuple[str | None, str, list[str]]:
    attempts = [name]
    candidates: set[str] = set()
    original_html = fetch(SEARCH_URL.format(quote(name)))
    profile_url, method = parse_search_html(original_html, name)
    if profile_url:
        return profile_url, method, [SEARCH_URL.format(quote(name))]
    tokens = name.split()
    for size in range(len(tokens) - 1, 1, -1):
        for parts in itertools.combinations(tokens, size):
            query = " ".join(parts)
            if query not in attempts:
                attempts.append(query)
            if len(attempts) >= 7:
                break
        if len(attempts) >= 7:
            break
    urls = [SEARCH_URL.format(quote(query)) for query in attempts]
    for url in urls[1:]:
        candidate, candidate_method = parse_search_html(fetch(url), name)
        if candidate and candidate_method in {
            "EXACT_NORMALIZED_TOKEN_SET_NAME", "UNIQUE_MULTI_TOKEN_SUBSET_ALIAS"
        }:
            candidates.add(candidate)
    if len(candidates) == 1:
        return candidates.pop(), "UNIQUE_MULTI_TOKEN_SUBSET_ALIAS_FALLBACK_SEARCH", urls
    if len(candidates) > 1:
        return None, "AMBIGUOUS_FALLBACK_SEARCH_CANDIDATES", urls
    return None, method, urls


def roster_from_universe(path: str) -> list[dict]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    roster: dict[str, dict] = {}
    for event in payload.get("events", {}).get("TENNIS_SINGLES") or []:
        for side in ("home", "away"):
            player = event.get(side) or {}
            player_id = str(player.get("id") or "").strip()
            name = str(player.get("name") or "").strip()
            if player_id and name:
                roster[player_id] = {
                    "provider_player_id": player_id,
                    "canonical_name": name,
                    "provider_country_code": player.get("cc") or UNKNOWN,
                }
    return sorted(roster.values(), key=lambda row: (ranking_key(row["canonical_name"]), row["provider_player_id"]))


def load_previous_profiles(path: str | None) -> tuple[dict[str, dict], str | None]:
    if not path or not Path(path).exists():
        return {}, None
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if payload.get("stage") != "TENNIS_PLAYER_STATIC_PROFILE_SNAPSHOT":
        raise ValueError("previous profile registry has incompatible stage")
    profiles: dict[str, dict] = {}
    for row in payload.get("players") or []:
        player_id = str(row.get("provider_player_id") or "").strip()
        if player_id:
            profiles[player_id] = row
    return profiles, payload.get("retrieved_at_utc")


def reusable_profile(previous: dict | None, roster: dict) -> bool:
    return bool(
        previous
        and previous.get("status") == "RESOLVED"
        and str(previous.get("provider_player_id") or "") == str(roster.get("provider_player_id") or "")
        and ranking_key(previous.get("canonical_name")) == ranking_key(roster.get("canonical_name"))
        and isinstance(previous.get("fields"), dict)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--previous-profile-snapshot")
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    args = parser.parse_args()

    previous, previous_retrieved_at = load_previous_profiles(args.previous_profile_snapshot)
    registry = dict(previous)
    current_players = []
    reused = fetched = 0
    retrieved_at = iso_now()
    for roster in roster_from_universe(args.universe):
        name = roster["canonical_name"]
        search_url = SEARCH_URL.format(quote(name))
        cached = previous.get(roster["provider_player_id"])
        if reusable_profile(cached, roster):
            record = {
                **cached,
                **roster,
                "profile_cache_status": "REUSED_PERSISTENT_PROFILE",
                "profile_retrieved_at_utc": (
                    cached.get("profile_retrieved_at_utc") or previous_retrieved_at or UNKNOWN
                ),
            }
            registry[roster["provider_player_id"]] = record
            current_players.append(record)
            reused += 1
            continue
        try:
            profile_url, method, search_attempts = resolve_profile_url(name)
            if not profile_url:
                record = {
                    **roster, "status": "UNRESOLVED", "resolution_method": method,
                    "source": SOURCE_NAME, "search_url": search_url, "profile_url": UNKNOWN,
                    "search_attempts": search_attempts, "fields": {},
                    "profile_cache_status": "FETCHED_CURRENT_RUN",
                    "profile_retrieved_at_utc": retrieved_at,
                }
            else:
                fields = parse_profile_html(fetch(profile_url))
                record = {
                    **roster, "status": "RESOLVED", "resolution_method": method,
                    "source": SOURCE_NAME, "search_url": search_url, "profile_url": profile_url,
                    "search_attempts": search_attempts, "fields": fields,
                    "profile_cache_status": "FETCHED_CURRENT_RUN",
                    "profile_retrieved_at_utc": retrieved_at,
                }
        except RuntimeError as exc:
            record = {
                **roster, "status": "TECHNICAL_ERROR", "resolution_method": "FETCH_FAILED",
                "source": SOURCE_NAME, "search_url": search_url, "profile_url": UNKNOWN,
                "fields": {}, "error": str(exc),
                "profile_cache_status": "FETCHED_CURRENT_RUN",
                "profile_retrieved_at_utc": retrieved_at,
            }
        registry[roster["provider_player_id"]] = record
        current_players.append(record)
        fetched += 1
        time.sleep(max(0.0, args.delay_seconds))

    resolved = sum(row["status"] == "RESOLVED" for row in current_players)
    output = {
        "schema_version": 2,
        "stage": "TENNIS_PLAYER_STATIC_PROFILE_SNAPSHOT",
        "source": SOURCE_NAME,
        "source_url": BASE_URL + "/list-players/",
        "retrieved_at_utc": retrieved_at,
        "players_requested": len(current_players),
        "profiles_resolved": resolved,
        "profiles_reused": reused,
        "profiles_fetched": fetched,
        "registry_players": len(registry),
        "players": sorted(
            registry.values(),
            key=lambda row: (ranking_key(row.get("canonical_name")), str(row.get("provider_player_id") or "")),
        ),
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "players_requested": len(current_players), "profiles_resolved": resolved,
        "profiles_reused": reused, "profiles_fetched": fetched, "registry_players": len(registry),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
