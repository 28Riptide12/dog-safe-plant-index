"""Harvest per-plant toxicity evidence into database/plant_toxicity_evidence.json.

Review-first behavior:
- Preserves existing evidence entries unless --overwrite is used.
- Can run without remote requests (seed from local plant records only).
- Optional source-page fetch adds quote snippets with explicit provenance.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parents[1]
PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
OUTPUT_PATH = BASE_DIR / "database" / "plant_toxicity_evidence.json"
USER_AGENT = "TopsoilPlantGuideToxicityHarvester/1.0 (+local)"

SOURCE_META = {
    "aspca.org": {"source_name": "ASPCA", "source_type": "veterinary-toxicology", "confidence": "high"},
    "petpoisonhelpline.com": {"source_name": "Pet Poison Helpline", "source_type": "veterinary-toxicology", "confidence": "high"},
    "vcahospitals.com": {"source_name": "VCA Animal Hospitals", "source_type": "veterinary-toxicology", "confidence": "high"},
    "animalemergencyservice.com.au": {"source_name": "Animal Emergency Service", "source_type": "veterinary-toxicology", "confidence": "medium"},
    "rhs.org.uk": {"source_name": "RHS", "source_type": "horticulture", "confidence": "medium"},
    "gardenersworld.com": {"source_name": "Gardener's World", "source_type": "horticulture", "confidence": "medium"},
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def source_meta(url: str) -> dict[str, str]:
    host = (urlparse(str(url or "")).netloc or "").casefold().strip(".")
    if host.startswith("www."):
        host = host[4:]
    for domain, meta in SOURCE_META.items():
        if host == domain or host.endswith(f".{domain}"):
            return {"source_domain": domain, **meta}
    return {
        "source_domain": host or "",
        "source_name": host or "Unknown source",
        "source_type": "unclassified",
        "confidence": "low",
    }


def severity_from_safety_status(status: str) -> str:
    value = str(status or "").strip().casefold()
    if value == "non-toxic to dogs":
        return "none"
    if value == "may be toxic":
        return "mild"
    if value == "toxic":
        return "severe"
    return "unknown"


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def infer_animal_severity(text: str, animal: str, fallback: str = "unknown") -> str:
    t = clean_space(text).casefold()
    if not t:
        return fallback
    if re.search(rf"\bnon[-\s]?toxic to {animal}\b", t):
        return "none"
    if animal == "dogs" and re.search(r"\bdogs?\b", t):
        if "mild" in t and ("upset" in t or "gastro" in t):
            return "mild"
        if "severe" in t or "life-threatening" in t or "fatal" in t:
            return "severe"
    if animal == "cats" and re.search(r"\bcats?\b", t):
        if "highly toxic" in t or "severe" in t or "fatal" in t:
            return "severe"
        if "mild" in t:
            return "mild"
    return fallback


def fetch_source_text(url: str, timeout: float) -> str:
    if not str(url).startswith("http"):
        return ""
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.extract()
    return clean_space(soup.get_text(" "))


def toxicity_quote_from_text(text: str) -> str:
    if not text:
        return ""
    # Keep this conservative: capture the first short toxicity-like sentence fragment.
    patterns = [
        r"([^.]{0,220}\bnon[-\s]?toxic to dogs\b[^.]{0,220}\.)",
        r"([^.]{0,220}\btoxic\b[^.]{0,220}\.)",
        r"([^.]{0,220}\bgastro(?:intestinal)?\s+upset\b[^.]{0,220}\.)",
        r"([^.]{0,220}\blil(?:y|ies)\b[^.]{0,220}\.)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_space(match.group(1))
    return ""


def build_seed_evidence(plant: dict[str, Any]) -> dict[str, Any]:
    url = str(plant.get("source_url", "")).strip()
    meta = source_meta(url)
    description = clean_space(str(plant.get("description", "")))
    status_note = clean_space(str(plant.get("source_status", "")))
    toxicity_details = clean_space(str(plant.get("toxicity_details", "")))
    quote = description or status_note or toxicity_details or "Seeded from existing plant record."
    dog_fallback = severity_from_safety_status(plant.get("safety_status", ""))
    combined = " ".join(item for item in [description, status_note, toxicity_details] if item)
    return {
        "source_url": url,
        "source_name": meta["source_name"],
        "source_type": meta["source_type"],
        "dog_severity": infer_animal_severity(combined, "dogs", fallback=dog_fallback),
        "cat_severity": infer_animal_severity(combined, "cats", fallback="unknown"),
        "quote": quote,
        "confidence": meta["confidence"],
        "last_checked_at": now_iso(),
        "method": "seed-from-local-record",
    }


def build_fetched_evidence(plant: dict[str, Any], page_text: str) -> dict[str, Any] | None:
    source_url = str(plant.get("source_url", "")).strip()
    quote = toxicity_quote_from_text(page_text)
    if not quote:
        return None
    meta = source_meta(source_url)
    dog_fallback = severity_from_safety_status(plant.get("safety_status", ""))
    return {
        "source_url": source_url,
        "source_name": meta["source_name"],
        "source_type": meta["source_type"],
        "dog_severity": infer_animal_severity(quote, "dogs", fallback=dog_fallback),
        "cat_severity": infer_animal_severity(quote, "cats", fallback="unknown"),
        "quote": quote,
        "confidence": meta["confidence"],
        "last_checked_at": now_iso(),
        "method": "fetched-page-snippet",
    }


def dedupe_evidence(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for entry in entries:
        key = (
            str(entry.get("source_url", "")).strip(),
            str(entry.get("method", "")).strip(),
            str(entry.get("dog_severity", "")).strip(),
            str(entry.get("quote", "")).strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harvest toxicity evidence into database/plant_toxicity_evidence.json")
    parser.add_argument("--plants", type=Path, default=PLANTS_PATH, help="Path to dog_safe_plants.json")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to plant_toxicity_evidence.json")
    parser.add_argument("--limit", type=int, default=120, help="Max plants to process when --id is not provided")
    parser.add_argument("--id", dest="ids", action="append", default=[], help="Plant ID(s) to process (repeatable)")
    parser.add_argument("--fetch-source", action="store_true", help="Fetch source URLs and add quote snippets")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds for fetch mode")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between source fetches")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing evidence for selected plants")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plants_doc = read_json(args.plants, {"plants": []})
    plants = plants_doc.get("plants", [])
    if not isinstance(plants, list):
        raise SystemExit("Invalid plants payload: expected top-level plants array.")

    output_doc = read_json(
        args.output,
        {
            "version": "1.0",
            "generated_at": None,
            "description": "Per-plant toxicity evidence records for dogs/cats with provenance and confidence.",
            "plants": {},
        },
    )
    existing_records = output_doc.get("plants", {})
    if not isinstance(existing_records, dict):
        existing_records = {}

    selected_ids = {item.strip() for item in args.ids if item.strip()}
    selected: list[dict[str, Any]] = []
    for plant in plants:
        if not isinstance(plant, dict) or not plant.get("id"):
            continue
        if selected_ids and plant.get("id") not in selected_ids:
            continue
        selected.append(plant)
        if not selected_ids and len(selected) >= max(1, args.limit):
            break

    updated = 0
    warnings: list[str] = []
    for index, plant in enumerate(selected, start=1):
        plant_id = str(plant.get("id"))
        current = dict(existing_records.get(plant_id) or {})
        evidence: list[dict[str, Any]] = [] if args.overwrite else list(current.get("evidence", []))
        evidence.append(build_seed_evidence(plant))

        if args.fetch_source:
            source_url = str(plant.get("source_url", "")).strip()
            if source_url.startswith("http"):
                try:
                    page_text = fetch_source_text(source_url, timeout=args.timeout)
                    fetched = build_fetched_evidence(plant, page_text)
                    if fetched:
                        evidence.append(fetched)
                except requests.RequestException as error:
                    warnings.append(f"{plant_id}: {error}")
                time.sleep(max(0.0, args.delay))

        merged = {
            "name": str(plant.get("name", "")).strip(),
            "scientific_name": str(plant.get("scientific_name", "")).strip(),
            "safety_status_current": str(plant.get("safety_status", "")).strip(),
            "evidence": dedupe_evidence(evidence),
            "_meta": {
                "updated_at": now_iso(),
                "source_url": str(plant.get("source_url", "")).strip(),
            },
        }
        if merged != current:
            existing_records[plant_id] = merged
            updated += 1

        if index % 25 == 0:
            print(f"Processed {index}/{len(selected)} plants...")

    output_doc["generated_at"] = now_iso()
    output_doc["plants"] = existing_records

    if args.dry_run:
        print("Dry run only - no file changes written.")
    else:
        write_json(args.output, output_doc)
        print(f"Wrote toxicity evidence: {args.output}")

    print(f"Plants processed: {len(selected)}")
    print(f"Plant records updated: {updated}")
    if warnings:
        print(f"Fetch warnings: {len(warnings)}")
        for line in warnings[:20]:
            print(f" - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
