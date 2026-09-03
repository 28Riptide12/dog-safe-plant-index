"""Harvest lifecycle and hardiness facts into database/plant_lifecycle_and_hardiness.json.

This file is designed for review-first botanical data curation:
- seeds from the local plant record
- optionally fetches the plant source page for extra evidence
- preserves existing entries unless --overwrite is used
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
OUTPUT_PATH = BASE_DIR / "database" / "plant_lifecycle_and_hardiness.json"
USER_AGENT = "TopsoilPlantGuideLifecycleHarvester/1.0 (+local)"

SOURCE_META = {
    "aspca.org": {"source_name": "ASPCA", "source_type": "veterinary-toxicology", "confidence": "high"},
    "rhs.org.uk": {"source_name": "RHS", "source_type": "horticulture", "confidence": "medium"},
    "gardenersworld.com": {"source_name": "Gardener's World", "source_type": "horticulture", "confidence": "medium"},
    "petpoisonhelpline.com": {"source_name": "Pet Poison Helpline", "source_type": "veterinary-toxicology", "confidence": "high"},
    "vcahospitals.com": {"source_name": "VCA Animal Hospitals", "source_type": "veterinary-toxicology", "confidence": "high"},
    "animalemergencyservice.com.au": {"source_name": "Animal Emergency Service", "source_type": "veterinary-toxicology", "confidence": "medium"},
}

ANNUAL_WORDS = ("annual", "hardy annual", "half-hardy annual", "half hardy annual", "tender annual")
LIFECYCLE_PATTERNS = {
    "annual": r"\b(hardy annual|half[-\s]?hardy annual|tender annual|annual)\b",
    "biennial": r"\bbiennial\b",
    "perennial": r"\b(short[-\s]?lived perennial|perennial)\b",
    "bulb": r"\b(bulb|corm|tuber|rhizome)\b",
    "shrub": r"\b(shrub|woody perennial)\b",
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


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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


def fetch_source_text(url: str, timeout: float) -> str:
    if not str(url).startswith("http"):
        return ""
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.extract()
    return clean_space(soup.get_text(" "))


def find_first(patterns: list[str], text: str, flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            return clean_space(value)
    return ""


def infer_lifecycle_details(plant: dict[str, Any], page_text: str) -> dict[str, str]:
    blob = clean_space(
        " ".join(
            [
                str(plant.get("name", "")),
                str(plant.get("scientific_name", "")),
                str(plant.get("description", "")),
                str(plant.get("growth_habit", "")),
                str(plant.get("care_notes", "")),
                page_text,
            ]
        )
    ).casefold()
    hardiness = clean_space(str(plant.get("hardiness_zone", plant.get("hardiness_zones_uk", "")))).upper()

    lifecycle = "Perennial"
    if re.search(LIFECYCLE_PATTERNS["annual"], blob):
        lifecycle = "Annual"
    if re.search(LIFECYCLE_PATTERNS["biennial"], blob):
        lifecycle = "Biennial"
    if re.search(LIFECYCLE_PATTERNS["perennial"], blob):
        lifecycle = "Perennial"
    if re.search(LIFECYCLE_PATTERNS["bulb"], blob):
        lifecycle = "Bulb"
    if re.search(LIFECYCLE_PATTERNS["shrub"], blob):
        lifecycle = "Shrub"

    if "short-lived perennial" in blob or "short lived perennial" in blob:
        lifecycle = "Short-lived perennial"

    if lifecycle == "Annual":
        if "hardy annual" in blob or hardiness in {"H3", "H4", "H5", "H6", "H7"}:
            subtype = "Hardy annual"
        elif "half-hardy" in blob or hardiness in {"H1A", "H1B", "H2"}:
            subtype = "Half-hardy annual"
        elif "tender" in blob or hardiness in {"H1A", "H1B"}:
            subtype = "Tender annual"
        else:
            subtype = "Annual"
    else:
        subtype = lifecycle

    if hardiness:
        if hardiness in {"H1A", "H1B"}:
            tenderness = "Frost-tender"
        elif hardiness in {"H2"}:
            tenderness = "Half-hardy"
        else:
            tenderness = "Hardy"
    elif "frost-tender" in blob or "half-hardy" in blob:
        tenderness = "Half-hardy"
    else:
        tenderness = "Hardy"

    if lifecycle == "Annual":
        if subtype == "Hardy annual":
            sowing = "Direct sow spring to early summer"
            winter = "Sow fresh each year; plants usually finish before frost"
        elif subtype == "Half-hardy annual":
            sowing = "Start under cover in spring; plant out after last frost"
            winter = "Treat as seasonal bedding; replant after frost risk"
        elif subtype == "Tender annual":
            sowing = "Start under cover in warmth; avoid frost"
            winter = "Keep frost-free or resow annually"
        else:
            sowing = "Spring sowing or as directed"
            winter = "Usually treated as a seasonal annual"
    elif lifecycle == "Biennial":
        sowing = "Sow spring or summer for flowering the following year"
        winter = "Usually survives one winter and flowers the next season"
    elif lifecycle == "Bulb":
        sowing = "Plant bulbs or offsets at the recommended season"
        winter = "Lift, store, or mulch depending on species hardiness"
    elif lifecycle == "Shrub":
        sowing = "Plant container-grown stock in spring or autumn"
        winter = "Mulch roots and protect young growth from frost"
    else:
        sowing = "Plant in spring or autumn when soil is workable"
        winter = "Overwinter outdoors if hardy; protect from severe frost if young"

    if "deadhead" in blob or "deadheading" in blob:
        deadheading = "Yes"
    elif lifecycle == "Annual":
        deadheading = "Often beneficial"
    elif "flower" in blob:
        deadheading = "Usually beneficial"
    else:
        deadheading = "Not usually"

    if "self-seeding" in blob or "self seeding" in blob or "seed freely" in blob:
        self_seed = "Moderate to high"
    elif lifecycle == "Annual":
        self_seed = "Low to moderate"
    else:
        self_seed = "Low"

    if "container" in blob or "pot" in blob:
        container = "Excellent"
    elif lifecycle in {"Annual", "Bulb"}:
        container = "Very good"
    else:
        container = "Possible with adequate pot size"

    return {
        "lifecycle": lifecycle,
        "lifecycle_subtype": subtype,
        "tenderness": tenderness,
        "sowing_window": sowing,
        "deadheading_needed": deadheading,
        "self_seeding_risk": self_seed,
        "container_suitability": container,
        "winter_handling": winter,
        "hardiness_zone": clean_space(str(plant.get("hardiness_zone", plant.get("hardiness_zones_uk", "")))) or "RHS H4",
        "sun_exposure": clean_space(str(plant.get("sun_exposure", ""))) or "",
        "soil_type": clean_space(str(plant.get("soil_preference", ""))) or "",
        "watering_needs": clean_space(str(plant.get("watering_needs", ""))) or "",
        "mature_size": clean_space(str(plant.get("mature_size", ""))) or "",
        "time_to_first_yield": clean_space(str(plant.get("time_to_first_yield", ""))) or "",
    }


def evidence_quote(text: str) -> str:
    patterns = [
        r"([^.]{0,220}\bhalf[-\s]?hardy annual\b[^.]{0,220}\.)",
        r"([^.]{0,220}\bhardy annual\b[^.]{0,220}\.)",
        r"([^.]{0,220}\btender annual\b[^.]{0,220}\.)",
        r"([^.]{0,220}\bdeadhead[^.]{0,220}\.)",
        r"([^.]{0,220}\bself[-\s]?seeding\b[^.]{0,220}\.)",
        r"([^.]{0,220}\bfrost[-\s]?tender\b[^.]{0,220}\.)",
        r"([^.]{0,220}\bcontainer\b[^.]{0,220}\.)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return clean_space(match.group(1))
    return ""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harvest lifecycle and hardiness data into database/plant_lifecycle_and_hardiness.json")
    parser.add_argument("--plants", type=Path, default=PLANTS_PATH, help="Path to dog_safe_plants.json")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH, help="Path to plant_lifecycle_and_hardiness.json")
    parser.add_argument("--limit", type=int, default=120, help="Max plants to process when --id is not provided")
    parser.add_argument("--id", dest="ids", action="append", default=[], help="Plant ID(s) to process (repeatable)")
    parser.add_argument("--fetch-source", action="store_true", help="Fetch source pages to improve lifecycle evidence")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between source fetches")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing entries for selected plants")
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
        {"version": "1.0", "generated_at": None, "description": "Per-plant lifecycle and hardiness facts with provenance.", "plants": {}},
    )
    records = output_doc.get("plants", {})
    if not isinstance(records, dict):
        records = {}

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
        existing = dict(records.get(plant_id) or {})
        source_url = clean_space(str(plant.get("source_url", "")))
        page_text = ""
        if args.fetch_source and source_url.startswith("http"):
            try:
                page_text = fetch_source_text(source_url, timeout=args.timeout)
            except requests.RequestException as error:
                warnings.append(f"{plant_id}: {error}")
            time.sleep(max(0.0, args.delay))

        data = infer_lifecycle_details(plant, page_text)
        meta = {
            "updated_at": now_iso(),
            "source_urls": [source_url] if source_url else [],
            "field_sources": {},
        }
        if page_text:
            quote = evidence_quote(page_text)
            if quote:
                meta["evidence_quote"] = quote
                meta["field_sources"] = {key: source_url or "derived" for key in ["lifecycle", "lifecycle_subtype", "tenderness", "sowing_window", "deadheading_needed", "self_seeding_risk", "container_suitability", "winter_handling"]}
        if source_url and not page_text:
            meta["field_sources"] = {key: source_url for key in ["lifecycle", "lifecycle_subtype", "tenderness", "sowing_window", "deadheading_needed", "self_seeding_risk", "container_suitability", "winter_handling"]}

        merged = {**existing, **data, "_meta": {**existing.get("_meta", {}), **meta}}
        if merged != existing:
            records[plant_id] = merged
            updated += 1

        if index % 25 == 0:
            print(f"Processed {index}/{len(selected)} plants...")

    output_doc["generated_at"] = now_iso()
    output_doc["plants"] = records

    if args.dry_run:
        print("Dry run only - no file changes written.")
    else:
        write_json(args.output, output_doc)
        print(f"Wrote lifecycle/hardiness data: {args.output}")

    print(f"Plants processed: {len(selected)}")
    print(f"Plant records updated: {updated}")
    if warnings:
        print(f"Fetch warnings: {len(warnings)}")
        for item in warnings[:20]:
            print(f" - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

