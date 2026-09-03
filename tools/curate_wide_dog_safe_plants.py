#!/usr/bin/env python3
"""
Curate the dog-safe plant catalogue.

- Deduplicate entries by canonical name/scientific name
- Preserve alternate names in the synonym store
- Optionally fill missing images using the local photo-suggestion API
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as appmod

BASE_DIR = Path(__file__).resolve().parent.parent
DATABASE_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
SYNONYMS_PATH = BASE_DIR / "database" / "plant_synonyms.json"
BACKUP_DIR = BASE_DIR / "backups"
API_BASE = "http://127.0.0.1:5050"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def canonical_group_key(plant: dict) -> str:
    scientific = appmod.scientific_key(plant.get("scientific_name"))
    if scientific:
        return f"sc:{scientific}"
    name = appmod.canonical_plant_name_key(plant.get("name"))
    if name:
        return f"name:{name}"
    return f"id:{appmod.canonical_plant_text(plant.get('id'))}"


def collect_aliases(group: list[dict]) -> list[str]:
    aliases = []
    for plant in group:
        for value in (plant.get("name"), plant.get("scientific_name"), plant.get("id")):
            text = str(value or "").strip()
            if text and text not in aliases:
                aliases.append(text)
    return aliases


def dedupe_catalogue(plants: list[dict]) -> tuple[list[dict], dict[str, list[str]]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for plant in plants:
        grouped[canonical_group_key(plant)].append(plant)

    deduped: list[dict] = []
    synonym_rows: dict[str, list[str]] = {}
    for group in grouped.values():
        rep = dict(group[0])
        for incoming in group[1:]:
            rep = appmod.merge_plant_records(rep, incoming)
        deduped.append(rep)
        aliases = collect_aliases(group)
        if len(aliases) > 1:
            synonym_rows[str(rep.get("id"))] = aliases
    deduped.sort(key=lambda item: str(item.get("name", "")).casefold())
    return deduped, synonym_rows


def merge_synonyms(existing: dict, generated: dict[str, list[str]]) -> dict:
    plants = existing.setdefault("plants", {})
    for plant_id, aliases in generated.items():
        current = dict(plants.get(plant_id) or {})
        merged_aliases = []
        for alias in [current.get("name"), current.get("scientific_name"), *(current.get("aliases") or []), *aliases]:
            text = str(alias or "").strip()
            if text and text not in merged_aliases:
                merged_aliases.append(text)
        plants[plant_id] = {
            "name": current.get("name") or aliases[0],
            "scientific_name": current.get("scientific_name") or "",
            "aliases": merged_aliases,
        }
    existing["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return existing


def fill_missing_images(plants: list[dict], limit: int, offset: int) -> int:
    queue = [plant for plant in plants if appmod.image_url_is_placeholder(plant.get("image_url", ""))]
    if offset:
        queue = queue[offset:]
    if limit:
        queue = queue[:limit]
    if not queue:
        return 0

    session = requests.Session()
    updated = 0
    for plant in queue:
        suggestion = session.get(
            f"{API_BASE}/api/dog-safe-plants/photo-suggestion",
            params={"name": plant.get("name", ""), "scientific_name": plant.get("scientific_name", "")},
            timeout=60,
        )
        if not suggestion.ok:
            continue
        data = suggestion.json()
        candidates = data.get("candidates") or [data]
        chosen = next((item for item in candidates if item.get("image_url") and item.get("source_url")), None)
        if not chosen:
            continue
        saved = session.post(
            f"{API_BASE}/api/dog-safe-plants/{plant['id']}/photo",
            json={"image_url": chosen["image_url"], "image_source_url": chosen["source_url"]},
            timeout=60,
        )
        if saved.ok:
            updated += 1
            print(f"[image] {plant['name']} -> {chosen.get('source_name') or 'source'}")
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate and enrich dog-safe plants")
    parser.add_argument("--fill-images", action="store_true", help="Fill missing images via photo suggestion")
    parser.add_argument("--limit", type=int, default=0, help="Limit image fills to N plants")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N missing-image plants")
    args = parser.parse_args()

    database = load_json(DATABASE_PATH)
    plants = database.get("plants", [])
    deduped, synonym_rows = dedupe_catalogue(plants)

    BACKUP_DIR.mkdir(exist_ok=True)
    backup_path = BACKUP_DIR / f"dog-safe-plants-curated-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    shutil.copy2(DATABASE_PATH, backup_path)

    database["plants"] = deduped
    database["source"] = database.get("source", "curated")
    database["curated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    save_json(DATABASE_PATH, database)

    synonyms = load_json(SYNONYMS_PATH)
    merge_synonyms(synonyms, synonym_rows)
    save_json(SYNONYMS_PATH, synonyms)

    print(f"deduped {len(plants)} -> {len(deduped)} plants")
    print(f"synonym groups updated: {len(synonym_rows)}")
    print(f"backup: {backup_path}")

    if args.fill_images:
        updated = fill_missing_images(deduped, args.limit, args.offset)
        print(f"updated images: {updated}")


if __name__ == "__main__":
    main()
