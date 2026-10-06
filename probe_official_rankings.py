#!/usr/bin/env python3
"""Probe official ATP/WTA full-ranking publications against a player list."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(sorted(re.findall(r"[a-z0-9]+", value.lower())))


class ATPTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.row_depth = 0
        self.row_text: list[str] = []
        self.player_text: list[str] = []
        self.in_player_link = False
        self.rows: list[tuple[int, str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.row_depth += 1
            self.row_text = []
            self.player_text = []
        if self.in_row and tag == "a" and "/players/" in (attrs_dict.get("href") or ""):
            self.in_player_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.in_player_link = False
        if tag == "tr" and self.in_row:
            text = " ".join(self.row_text)
            rank_match = re.search(r"(?:^|\s)(\d{1,5})(?:\s|$)", text)
            player = " ".join(self.player_text).strip()
            if rank_match and player:
                self.rows.append((int(rank_match.group(1)), player, text))
            self.row_depth -= 1
            self.in_row = self.row_depth > 0

    def handle_data(self, data: str) -> None:
        if self.in_row:
            cleaned = " ".join(data.split())
            if cleaned:
                self.row_text.append(cleaned)
                if self.in_player_link:
                    self.player_text.append(cleaned)


def parse_atp(path: Path) -> list[dict]:
    parser = ATPTableParser()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    unique: dict[tuple[int, str], dict] = {}
    for rank, player, raw in parser.rows:
        unique[(rank, norm(player))] = {"rank": rank, "name": player, "raw": raw}
    return sorted(unique.values(), key=lambda row: (row["rank"], row["name"]))


def parse_wta(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*(\d{1,5})\s+\([^)]*\)\s+(.+?)\s+([A-Z]{3})\s+(\d+)\s+", line)
        if match:
            rows.append({
                "rank": int(match.group(1)),
                "name": match.group(2).strip(),
                "country": match.group(3),
                "points": int(match.group(4)),
                "raw": line.strip(),
            })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atp-html", required=True)
    parser.add_argument("--wta-text", required=True)
    parser.add_argument("--players", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    atp = parse_atp(Path(args.atp_html))
    wta = parse_wta(Path(args.wta_text))
    players = json.loads(Path(args.players).read_text(encoding="utf-8"))
    atp_by_name = {norm(row["name"]): row for row in atp}
    wta_by_name = {norm(row["name"]): row for row in wta}
    coverage = []
    for player in players:
        key = norm(player["name"])
        hit = atp_by_name.get(key)
        source = "ATP" if hit else None
        if not hit:
            hit = wta_by_name.get(key)
            source = "WTA" if hit else None
        coverage.append({**player, "source": source, "ranking": hit})

    result = {
        "atp": {"rows": len(atp), "max_rank": max((r["rank"] for r in atp), default=None)},
        "wta": {"rows": len(wta), "max_rank": max((r["rank"] for r in wta), default=None)},
        "players": len(players),
        "matched": sum(row["ranking"] is not None for row in coverage),
        "coverage": coverage,
    }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "coverage"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
