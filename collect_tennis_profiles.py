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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    args = parser.parse_args()

    players = []
    for roster in roster_from_universe(args.universe):
        name = roster["canonical_name"]
        search_url = SEARCH_URL.format(quote(name))
        try:
            profile_url, method, search_attempts = resolve_profile_url(name)
            if not profile_url:
                players.append({
                    **roster, "status": "UNRESOLVED", "resolution_method": method,
                    "source": SOURCE_NAME, "search_url": search_url, "profile_url": UNKNOWN,
                    "search_attempts": search_attempts, "fields": {},
                })
            else:
                fields = parse_profile_html(fetch(profile_url))
                players.append({
                    **roster, "status": "RESOLVED", "resolution_method": method,
                    "source": SOURCE_NAME, "search_url": search_url, "profile_url": profile_url,
                    "search_attempts": search_attempts, "fields": fields,
                })
        except RuntimeError as exc:
            players.append({
                **roster, "status": "TECHNICAL_ERROR", "resolution_method": "FETCH_FAILED",
                "source": SOURCE_NAME, "search_url": search_url, "profile_url": UNKNOWN,
                "fields": {}, "error": str(exc),
            })
        time.sleep(max(0.0, args.delay_seconds))

    resolved = sum(row["status"] == "RESOLVED" for row in players)
    output = {
        "schema_version": 1,
        "stage": "TENNIS_PLAYER_STATIC_PROFILE_SNAPSHOT",
        "source": SOURCE_NAME,
        "source_url": BASE_URL + "/list-players/",
        "retrieved_at_utc": iso_now(),
        "players_requested": len(players),
        "profiles_resolved": resolved,
        "players": players,
    }
    Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"players_requested": len(players), "profiles_resolved": resolved}, ensure_ascii=False))


if __name__ == "__main__":
    main()
