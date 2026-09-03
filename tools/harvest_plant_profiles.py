"""Harvest profile overrides for plant facts from trusted web pages.

This command enriches static/plant_profile_overrides.json using:
1) existing plant fields in dog_safe_plants.json
2) optional scraping of each plant's source_url page text

It is review-first:
- preserves manual overrides by default
- writes only fields with non-empty extracted values
- can run in --dry-run mode
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

BASE_DIR = Path(__file__).resolve().parents[1]
PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
OVERRIDES_PATH = BASE_DIR / "static" / "plant_profile_overrides.json"
USER_AGENT = "TopsoilPlantGuideProfileHarvester/1.0 (+local)"

CATEGORY_DEFAULTS: dict[str, dict[str, Any]] = {
    "flowers": {
        "sun_exposure": ["Full sun", "Partial shade"],
        "soil_type": "Well-draining, moist, loamy",
        "hardiness_zone": "RHS H4",
        "watering_needs": "Moderate",
    },
    "fruit": {
        "sun_exposure": ["Full sun"],
        "soil_type": "Rich, well-draining soil",
        "hardiness_zone": "RHS H4",
        "watering_needs": "Moderate",
    },
    "vegetables": {
        "sun_exposure": ["Full sun"],
        "soil_type": "Fertile, moisture-retentive soil",
        "hardiness_zone": "RHS H4",
        "watering_needs": "Moderate",
    },
    "herbs": {
        "sun_exposure": ["Full sun", "Partial shade"],
        "soil_type": "Light, well-draining soil",
        "hardiness_zone": "RHS H4",
        "watering_needs": "Moderate",
    },
    "grasses": {
        "sun_exposure": ["Full sun", "Partial shade"],
        "soil_type": "Well-draining soil suited to the variety",
        "hardiness_zone": "RHS H4",
        "watering_needs": "Low",
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def sentence(text: str) -> str:
    text = clean_space(text)
    if not text:
        return ""
    return text[0].upper() + text[1:]


def list_or_str(value: Any) -> str:
    if isinstance(value, list):
        parts = [clean_space(str(item)) for item in value if clean_space(str(item))]
        return ", ".join(parts)
    return clean_space(str(value or ""))


def is_default_like(category: str, field: str, value: str) -> bool:
    defaults = CATEGORY_DEFAULTS.get(category, {})
    default_value = defaults.get(field)
    if default_value is None:
        return False
    return list_or_str(default_value).casefold() == value.casefold()


def season_from_text(text: str) -> str:
    lower = text.casefold()
    seasons: list[str] = []
    if any(token in lower for token in ("spring", "mar", "april", "may")):
        seasons.append("Spring")
    if any(token in lower for token in ("summer", "jun", "july", "aug")):
        seasons.append("Summer")
    if any(token in lower for token in ("autumn", "fall", "sep", "oct", "nov")):
        seasons.append("Autumn")
    if any(token in lower for token in ("winter", "dec", "jan", "feb")):
        seasons.append("Winter")
    return ", ".join(dict.fromkeys(seasons))


def extract_first(patterns: list[str], text: str, flags: int = re.IGNORECASE) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return clean_space(match.group(1) if match.lastindex else match.group(0))
    return ""


def extract_many(patterns: list[str], text: str, flags: int = re.IGNORECASE) -> str:
    hits: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags):
            value = clean_space(match.group(1) if match.lastindex else match.group(0))
            if value and value.casefold() not in {item.casefold() for item in hits}:
                hits.append(value)
    return ", ".join(hits[:6])


def source_page_text(url: str, timeout: float) -> str:
    if not url.startswith("http"):
        return ""
    response = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for element in soup(["script", "style", "noscript"]):
        element.extract()
    return clean_space(soup.get_text(" "))


@dataclass
class HarvestResult:
    fields: dict[str, str]
    source_urls: list[str]
    field_sources: dict[str, str]


def harvest_fields(plant: dict[str, Any], page_text: str) -> HarvestResult:
    category = clean_space(str(plant.get("category", "")).lower())
    description = clean_space(str(plant.get("description", "")))
    local_blob = clean_space(
        " ".join(
            [
                str(plant.get("name", "")),
                str(plant.get("scientific_name", "")),
                description,
                str(plant.get("growth_habit", "")),
                str(plant.get("care_notes", "")),
            ]
        )
    )
    combined = clean_space(f"{local_blob} {page_text}")
    from_source = bool(page_text)
    source_url = clean_space(str(plant.get("source_url", "")))

    fields: dict[str, str] = {}
    field_sources: dict[str, str] = {}

    def pick(field: str, value: str, source: str) -> None:
        cleaned = sentence(value)
        if not cleaned:
            return
        fields[field] = cleaned
        field_sources[field] = source

    # Primary profile facts
    sun = extract_many([r"\b(full sun|partial shade|part shade|partial sun|full shade|bright indirect light)\b"], combined)
    soil = extract_many([r"\b(well-draining(?: soil)?|loamy(?: soil)?|sandy(?: soil)?|clay(?: soil)?|chalky(?: soil)?|moisture-retentive(?: soil)?)\b"], combined)
    watering = extract_first(
        [
            r"\b(drought-tolerant)\b",
            r"\b(low(?:\s+to\s+moderate)? water(?:ing)?(?: needs)?)\b",
            r"\b(moderate water(?:ing)?(?: needs)?)\b",
            r"\b(high water(?:ing)?(?: needs)?)\b",
            r"\b(keep (?:soil|compost) (?:consistently|evenly) moist)\b",
        ],
        combined,
    )
    hardiness = extract_first(
        [
            r"\b(RHS\s*H[1-7](?:[A-C])?)\b",
            r"\b((?:USDA\s*)?zones?\s*\d+\s*(?:[-–]\s*\d+)?)\b",
        ],
        combined,
    )
    habit = extract_first(
        [
            r"\b(clumping|spreading|upright|trailing|vining|mounding|rosette|arching)\b",
            r"\b(growth habit:\s*[^.;]+)",
        ],
        combined,
    )
    bloom = season_from_text(combined)

    height_cm = extract_first([r"\b(\d{2,3})\s*cm\s*(?:tall|high|height)\b"], combined)
    spread_cm = extract_first([r"\b(\d{2,3})\s*cm\s*(?:wide|spread)\b"], combined)
    mature_size = ""
    if height_cm or spread_cm:
        parts = []
        if height_cm:
            parts.append(f"Height {height_cm} cm")
        if spread_cm:
            parts.append(f"Spread {spread_cm} cm")
        mature_size = " · ".join(parts)

    foliage = extract_first([r"\b(evergreen|deciduous|semi-evergreen)\b"], combined)
    fragrance = extract_first([r"\b(scented flowers|aromatic foliage|fragrant|sweetly scented)\b"], combined)
    lifecycle = extract_first([r"\b(annual|biennial|perennial|bulb|shrub)\b"], combined)
    propagation = extract_many([r"\b(division|cuttings|self-seeding|seed|grafting|runners)\b"], combined)
    pollinator = extract_first([r"\b(high for bees|bee[- ]friendly|butterfly[- ]magnet|pollinator[- ]friendly)\b"], combined)
    wildlife = extract_first([r"\b(deer resistant|rabbit resistant|deer and rabbit resistant|susceptible to deer)\b"], combined)

    pests = extract_many([r"\b(powdery mildew|aphids?|slugs?|snails?|rust|black spot|root rot|mealybugs?)\b"], combined)

    # Derived practical fields
    companion = ""
    lower = combined.casefold()
    if "mint" in lower:
        companion = "Can spread aggressively; use a barrier or container."
    elif "spreading" in lower or "self-seeding" in lower:
        companion = "Can spread; monitor boundaries and thin as needed."
    else:
        companion = "Generally compatible when grouped by similar watering needs."

    pet_detail = ""
    safety = clean_space(str(plant.get("safety_status", ""))).casefold()
    if safety == "toxic":
        pet_detail = "Toxic if ingested; keep out of pet reach."
    elif any(token in lower for token in ("sharp blades", "coarse leaves", "grass")):
        pet_detail = "Non-toxic, but coarse/sharp foliage can cause mild mechanical irritation if heavily chewed."
    elif safety:
        pet_detail = "Non-toxic status from current source data; discourage heavy chewing."

    seasonal_interest = ""
    if bloom:
        seasonal_interest = f"{bloom} display period with strongest ornamental value in active season."
    elif category == "grasses":
        seasonal_interest = "Summer texture and autumn movement; winter structure if retained."

    garden_layer = ""
    if height_cm:
        h = int(height_cm)
        if h < 35:
            garden_layer = "Foreground/edging"
        elif h <= 90:
            garden_layer = "Mid-border"
        else:
            garden_layer = "Backdrop/tall"

    # Fill chosen fields
    if sun and not is_default_like(category, "sun_exposure", sun):
        pick("sun_exposure", sun, source_url if from_source else "local")
    if soil and not is_default_like(category, "soil_type", soil):
        pick("soil_type", soil, source_url if from_source else "local")
    if watering and not is_default_like(category, "watering_needs", watering):
        pick("watering_needs", watering, source_url if from_source else "local")
    if hardiness and not is_default_like(category, "hardiness_zone", hardiness):
        pick("hardiness_zone", hardiness, source_url if from_source else "local")
    if habit:
        pick("growth_habit", habit, source_url if from_source else "local")
    if mature_size:
        pick("mature_size", mature_size, source_url if from_source else "local")
    if bloom:
        pick("blooming_period", bloom, source_url if from_source else "local")
    if foliage:
        pick("foliage_type", foliage, source_url if from_source else "local")
    if seasonal_interest:
        pick("seasonal_interest", seasonal_interest, source_url if from_source else "local")
    if fragrance:
        pick("fragrance", fragrance, source_url if from_source else "local")
    if pollinator:
        pick("pollinator_value", pollinator, source_url if from_source else "local")
    if wildlife:
        pick("deer_rabbit_resistance", wildlife, source_url if from_source else "local")
    if lifecycle:
        pick("lifecycle", lifecycle, source_url if from_source else "local")
    if propagation:
        pick("propagation_method", propagation, source_url if from_source else "local")
    if pests:
        pick("common_pests_diseases", pests, source_url if from_source else "local")
    if companion:
        pick("companion_compatibility", companion, "derived")
    if pet_detail:
        pick("pet_safety_detail", pet_detail, "derived")
    if garden_layer:
        pick("garden_layer", garden_layer, "derived")

    best_use_tags: list[str] = []
    if "pollinator" in clean_space(fields.get("pollinator_value", "")).casefold():
        best_use_tags.append("pollinator border")
    if "container" in clean_space(fields.get("garden_layer", "")).casefold() or "container" in lower:
        best_use_tags.append("container")
    if category in {"vegetables", "fruit", "herbs"}:
        best_use_tags.append("edible patch")
    if "drought" in clean_space(fields.get("watering_needs", "")).casefold() or "low water" in clean_space(fields.get("watering_needs", "")).casefold():
        best_use_tags.append("low-water bed")
    if best_use_tags:
        fields["best_use_tags"] = json.dumps(best_use_tags)
        field_sources["best_use_tags"] = "derived"

    source_urls = [source_url] if source_url else []
    return HarvestResult(fields=fields, source_urls=source_urls, field_sources=field_sources)


def merge_override(existing: dict[str, Any], harvested: HarvestResult, overwrite: bool) -> dict[str, Any]:
    result = dict(existing)
    for key, value in harvested.fields.items():
        normalized_value: Any = value
        if key == "best_use_tags":
            try:
                normalized_value = json.loads(value)
            except json.JSONDecodeError:
                normalized_value = [value]
        if overwrite or not result.get(key):
            result[key] = normalized_value
    meta = dict(result.get("_meta") or {})
    meta["last_harvested_at"] = now_iso()
    if harvested.source_urls:
        meta["source_urls"] = sorted(set((meta.get("source_urls") or []) + harvested.source_urls))
    field_sources = dict(meta.get("field_sources") or {})
    for key, source in harvested.field_sources.items():
        if overwrite or key not in field_sources:
            field_sources[key] = source
    if field_sources:
        meta["field_sources"] = field_sources
    result["_meta"] = meta
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harvest profile overrides into static/plant_profile_overrides.json")
    parser.add_argument("--plants", type=Path, default=PLANTS_PATH, help="Path to dog_safe_plants.json")
    parser.add_argument("--overrides", type=Path, default=OVERRIDES_PATH, help="Path to plant_profile_overrides.json")
    parser.add_argument("--limit", type=int, default=60, help="Max plants to process")
    parser.add_argument("--id", dest="ids", action="append", default=[], help="Plant ID(s) to harvest (repeatable)")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout seconds")
    parser.add_argument("--delay", type=float, default=0.25, help="Delay between remote requests")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing override fields")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plants_doc = read_json(args.plants, {"plants": []})
    plants = plants_doc.get("plants", [])
    if not isinstance(plants, list):
        raise SystemExit("Invalid plants payload: expected top-level plants array.")

    overrides_doc = read_json(args.overrides, {"plants": {}})
    overrides_plants = overrides_doc.get("plants", {})
    if not isinstance(overrides_plants, dict):
        overrides_plants = {}

    selected: list[dict[str, Any]] = []
    ids = {item.strip() for item in args.ids if item.strip()}
    for plant in plants:
        if not isinstance(plant, dict) or not plant.get("id"):
            continue
        if ids and plant.get("id") not in ids:
            continue
        selected.append(plant)
        if not ids and len(selected) >= max(1, args.limit):
            break

    harvested_count = 0
    field_updates = 0
    errors: list[str] = []

    for index, plant in enumerate(selected, start=1):
        plant_id = str(plant.get("id"))
        source_url = clean_space(str(plant.get("source_url", "")))
        page_text = ""
        if source_url.startswith("http"):
            try:
                page_text = source_page_text(source_url, timeout=args.timeout)
            except requests.RequestException as error:
                errors.append(f"{plant_id}: {error}")
            time.sleep(max(0.0, args.delay))

        harvested = harvest_fields(plant, page_text)
        if not harvested.fields:
            continue
        existing = dict(overrides_plants.get(plant_id) or {})
        merged = merge_override(existing, harvested, overwrite=args.overwrite)
        if merged != existing:
            overrides_plants[plant_id] = merged
            harvested_count += 1
            field_updates += sum(1 for key in harvested.fields.keys() if args.overwrite or not existing.get(key))
        if index % 10 == 0:
            print(f"Processed {index}/{len(selected)} plants...")

    output_doc = {"plants": overrides_plants}
    if args.dry_run:
        print("Dry run only — no file changes written.")
    else:
        write_json(args.overrides, output_doc)
        print(f"Wrote overrides: {args.overrides}")

    print(f"Plants processed: {len(selected)}")
    print(f"Plants updated: {harvested_count}")
    print(f"Fields updated: {field_updates}")
    if errors:
        print(f"Source fetch warnings: {len(errors)}")
        for item in errors[:20]:
            print(f" - {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
