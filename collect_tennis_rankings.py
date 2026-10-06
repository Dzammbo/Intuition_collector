#!/usr/bin/env python3
"""Collect BetsAPI tennis singles rankings and state their coverage honestly."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


BASE_URL = "https://api.b365api.com/v1/tennis/ranking"
SINGLES_TYPES = (1, 3)


class RankingCollectionError(RuntimeError):
    pass


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def page_signature(rows: list[dict]) -> tuple[str, ...]:
    return tuple(str(row.get("id") or "") for row in rows)


def collect_ranking_type(
    type_id: int,
    fetch_page: Callable[[int, int], dict],
    allow_provider_single_page: bool = False,
) -> dict:
    """Read pages until the provider proves completion.

    Completion is accepted only when the response becomes empty or the pager's
    reported total is reached. A repeated non-empty page is an error, because
    silently accepting it would recreate the old first-page-only defect.
    """
    page = 1
    rows_by_id: dict[str, dict] = {}
    seen_signatures: set[tuple[str, ...]] = set()
    pages: list[dict] = []
    reported_total: int | None = None

    while True:
        payload = fetch_page(type_id, page)
        if not isinstance(payload, dict) or payload.get("success") != 1:
            raise RankingCollectionError(
                f"ranking type_id={type_id} page={page} returned unsuccessful payload"
            )
        rows = payload.get("results")
        if not isinstance(rows, list):
            raise RankingCollectionError(
                f"ranking type_id={type_id} page={page} has no results list"
            )

        pager = payload.get("pager") if isinstance(payload.get("pager"), dict) else {}
        if pager.get("total") not in (None, ""):
            try:
                reported_total = int(pager["total"])
            except (TypeError, ValueError) as exc:
                raise RankingCollectionError(
                    f"ranking type_id={type_id} page={page} has invalid pager.total"
                ) from exc

        signature = page_signature(rows)
        if rows and signature in seen_signatures:
            if not allow_provider_single_page:
                raise RankingCollectionError(
                    f"ranking type_id={type_id} repeated page content at page={page}; "
                    "provider pagination is not verified"
                )
            completion_reason = "PROVIDER_PAGINATION_UNSUPPORTED_REPEATED_FIRST_PAGE"
            pagination_complete = False
            provider_response_complete = True
            break
        if rows:
            seen_signatures.add(signature)

        before = len(rows_by_id)
        for row in rows:
            player_id = str(row.get("id") or "").strip()
            if player_id:
                rows_by_id[player_id] = row
        pages.append({
            "page": page,
            "rows_received": len(rows),
            "unique_rows_added": len(rows_by_id) - before,
            "pager": pager or None,
        })

        if not rows:
            completion_reason = "EMPTY_PAGE"
            pagination_complete = True
            provider_response_complete = True
            break
        if reported_total is not None and len(rows_by_id) >= reported_total:
            completion_reason = "PAGER_TOTAL_REACHED"
            pagination_complete = True
            provider_response_complete = True
            break
        page += 1

    return {
        "schema_version": 1,
        "source": "BETSAPI_TENNIS_RANKING",
        "type_id": type_id,
        "pagination_complete": pagination_complete,
        "provider_response_complete": provider_response_complete,
        "full_ranking_coverage": pagination_complete,
        "completion_reason": completion_reason,
        "pages_requested": len(pages),
        "reported_total": reported_total,
        "unique_rows": len(rows_by_id),
        "pages": pages,
        "results": list(rows_by_id.values()),
    }


def make_fetcher(token: str, retries: int = 3, timeout: int = 30):
    def fetch(type_id: int, page: int) -> dict:
        query = urllib.parse.urlencode({"token": token, "type_id": type_id, "page": page})
        request = urllib.request.Request(
            BASE_URL + "?" + query,
            headers={"User-Agent": "jarvis-intuition-ranking-collector/1.0"},
        )
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    return json.load(response)
            except Exception as exc:  # network boundary
                last_error = exc
                if attempt < retries:
                    time.sleep(1.5 * (attempt + 1))
        raise RankingCollectionError(
            f"ranking type_id={type_id} page={page} request failed: {last_error}"
        )

    return fetch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="rankings")
    parser.add_argument(
        "--allow-provider-single-page",
        action="store_true",
        help="Diagnostic only: accept the provider-published first response when page=2 repeats it",
    )
    args = parser.parse_args()

    token = os.environ.get("BETSAPI_TOKEN")
    if not token:
        raise SystemExit("BETSAPI_TOKEN is required")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = iso_now()
    manifest = {
        "schema_version": 1,
        "stage": "COMPLETE_TENNIS_SINGLES_RANKING_SNAPSHOT",
        "retrieved_at_utc": retrieved_at,
        "types": [],
    }
    fetch_page = make_fetcher(token)
    for type_id in SINGLES_TYPES:
        snapshot = collect_ranking_type(
            type_id,
            fetch_page,
            allow_provider_single_page=args.allow_provider_single_page,
        )
        snapshot["retrieved_at_utc"] = retrieved_at
        path = output_dir / f"betsapi-ranking-{type_id}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest["types"].append({
            "type_id": type_id,
            "file": path.name,
            "pagination_complete": snapshot["pagination_complete"],
            "provider_response_complete": snapshot["provider_response_complete"],
            "full_ranking_coverage": snapshot["full_ranking_coverage"],
            "pages_requested": snapshot["pages_requested"],
            "reported_total": snapshot["reported_total"],
            "unique_rows": snapshot["unique_rows"],
        })

    manifest["pagination_complete"] = all(item["pagination_complete"] for item in manifest["types"])
    manifest["provider_responses_complete"] = all(
        item["provider_response_complete"] for item in manifest["types"]
    )
    manifest["full_ranking_coverage"] = all(
        item["full_ranking_coverage"] for item in manifest["types"]
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
