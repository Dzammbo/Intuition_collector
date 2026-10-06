#!/usr/bin/env python3
"""Build complete ATP and WTA singles ranking snapshots from downloaded publications."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


ATP_SOURCE_URL = "https://www.tennisexplorer.com/ranking/atp-men/"
WTA_SOURCE_URL = "https://wtafiles.wtatennis.com/pdf/rankings/Singles_Numeric.pdf"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ranking_key(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(sorted(re.findall(r"[a-z0-9]+", text.casefold())))


class ATPTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_row = False
        self.row_text: list[str] = []
        self.player_text: list[str] = []
        self.in_player_link = False
        self.rows: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = dict(attrs)
        if tag == "tr":
            self.in_row = True
            self.row_text = []
            self.player_text = []
        href = attrs_dict.get("href") or ""
        if self.in_row and tag == "a" and "/player/" in href:
            self.in_player_link = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.in_player_link = False
        if tag == "tr" and self.in_row:
            raw = " ".join(self.row_text)
            rank_match = re.match(r"^\s*(\d{1,5})\.", raw)
            name = " ".join(self.player_text).strip()
            if rank_match and name:
                self.rows.append({
                    "name": name,
                    "ranking": int(rank_match.group(1)),
                    "points": None,
                    "country": None,
                    "tour": "ATP",
                    "raw": raw,
                })
            self.in_row = False

    def handle_data(self, data: str) -> None:
        if not self.in_row:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self.row_text.append(cleaned)
            if self.in_player_link:
                self.player_text.append(cleaned)


def parse_atp_html(path: str | Path) -> list[dict]:
    parser = ATPTableParser()
    parser.feed(Path(path).read_text(encoding="utf-8", errors="replace"))
    unique: dict[tuple[int, str], dict] = {}
    for row in parser.rows:
        unique[(row["ranking"], ranking_key(row["name"]))] = row
    return sorted(unique.values(), key=lambda row: (row["ranking"], row["name"]))


def parse_wta_text(path: str | Path) -> list[dict]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.match(r"^\s*(\d{1,5})\s+\([^)]*\)\s+(.+?)\s+([A-Z]{3})\s+(\d+)\s+", line)
        if match:
            rows.append({
                "name": match.group(2).strip(),
                "ranking": int(match.group(1)),
                "country": match.group(3),
                "points": int(match.group(4)),
                "tour": "WTA",
                "raw": line.strip(),
            })
    return rows


def snapshot(source: str, source_url: str, rows: list[dict], retrieved_at: str, pages: int | None) -> dict:
    return {
        "schema_version": 2,
        "source": source,
        "source_url": source_url,
        "retrieved_at_utc": retrieved_at,
        "provider_response_complete": True,
        "full_ranking_coverage": True,
        "pages_requested": pages,
        "unique_rows": len(rows),
        "max_rank": max((row["ranking"] for row in rows), default=None),
        "results": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atp-html", required=True)
    parser.add_argument("--wta-text", required=True)
    parser.add_argument("--atp-pages", type=int, default=50)
    parser.add_argument("--output-dir", default="rankings")
    args = parser.parse_args()

    atp = parse_atp_html(args.atp_html)
    wta = parse_wta_text(args.wta_text)
    if len(atp) < 2000 or max((row["ranking"] for row in atp), default=0) < 2000:
        raise SystemExit(f"ATP ranking is unexpectedly incomplete: rows={len(atp)}")
    if len(wta) < 1300 or max((row["ranking"] for row in wta), default=0) < 1400:
        raise SystemExit(f"WTA ranking is unexpectedly incomplete: rows={len(wta)}")

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    retrieved_at = iso_now()
    snapshots = [
        ("atp-ranking.json", snapshot(
            "TENNISEXPLORER_ATP_COMPLETE_RANKING", ATP_SOURCE_URL, atp, retrieved_at, args.atp_pages
        )),
        ("wta-ranking.json", snapshot(
            "WTA_OFFICIAL_SINGLES_NUMERIC_PDF", WTA_SOURCE_URL, wta, retrieved_at, None
        )),
    ]
    for filename, payload in snapshots:
        (output / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    manifest = {
        "schema_version": 2,
        "stage": "COMPLETE_TENNIS_SINGLES_RANKING_SNAPSHOT",
        "retrieved_at_utc": retrieved_at,
        "full_ranking_coverage": True,
        "sources": [{
            "source": payload["source"],
            "file": filename,
            "rows": payload["unique_rows"],
            "max_rank": payload["max_rank"],
            "full_ranking_coverage": True,
        } for filename, payload in snapshots],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
