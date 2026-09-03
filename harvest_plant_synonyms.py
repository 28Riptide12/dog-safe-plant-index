"""Harvest common-name synonyms/aliases for the catalogue from open taxonomy sources.

This is alias-only enrichment: it never touches safety_status, never adds new
plants, and never writes to the live catalogue or the review queue. It only
appends new candidate common-name aliases to database/plant_synonyms.json for
plants that already exist in database/dog_safe_plants.json, which directly
powers the search/alias engine in static/plants.js.

Sources used (all free, no API key required):
- GBIF Species API: vernacular names + accepted/synonym scientific names.
- Wikidata SPARQL: multilingual labels + "also known as" aliases for the taxon.
- iNaturalist taxa API: common names attached to the matched taxon.

Usage:
  python harvest_plant_synonyms.py                # harvest for every catalogue plant
  python harvest_plant_synonyms.py --limit 50      # harvest for the first 50 plants
  python harvest_plant_synonyms.py --plant-id rose # harvest for one plant id
  python harvest_plant_synonyms.py --dry-run        # print what would change, write nothing
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import requests

BASE_DIR = Path(__file__).resolve().parent
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
SYNONYMS_PATH = BASE_DIR / "database" / "plant_synonyms.json"
HEADERS = {"User-Agent": "TopsoilPlantGuide/1.0 (alias harvester; research catalogue)"}
REQUEST_TIMEOUT_SECONDS = 15
MAX_ALIASES_PER_PLANT = 40
# Only harvest aliases in these languages from Wikidata to avoid noisy/irrelevant scripts.
WIKIDATA_LANGUAGES = ("en",)


def clean_alias(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_usable_alias(value: str) -> bool:
    """Reject malformed source strings (e.g. multi-language dumps, empty/odd tokens)."""
    text = clean_alias(value)
    if not text or len(text) > 60:
        return False
    # Reject strings that bundle multiple names/languages, e.g. "Castor Bean (EN); Tartago (ES)".
    if ";" in text or "|" in text:
        return False
    if re.search(r"\((?:EN|ES|FR|DE|PT|IT|NL|RU|ZH|JA)\)", text, re.I):
        return False
    # Reject region/country-annotated names, e.g. "Aluminio (Dominican Republic)".
    if re.search(r"\([A-Za-z][A-Za-z .]{3,}\)$", text):
        return False
    # Reject mojibake/replacement characters and non-Latin scripts (e.g. pinyin romanizations, garbled encodings).
    if "\ufffd" in text or re.search(r"[\u0080-\uffff]", text):
        return False
    return True


def alias_key(value: str) -> str:
    """Case/punctuation-insensitive key used to dedupe aliases."""
    return re.sub(r"[^a-z0-9]+", " ", clean_alias(value).casefold()).strip()


def request_with_retry(url: str, *, params: dict | None = None, retries: int = 2, base_backoff: float = 0.6) -> requests.Response:
    delay = base_backoff
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt >= retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                time.sleep(wait)
                delay *= 2
                continue
            return response
        except requests.RequestException as error:
            last_error = error
            if attempt >= retries:
                raise
            time.sleep(delay)
            delay *= 2
    if last_error:
        raise last_error
    raise RuntimeError("Request retry failed without explicit error.")


def gbif_aliases(scientific_name: str) -> tuple[list[str], list[str]]:
    """Return (common_name_aliases, scientific_name_aliases) from GBIF."""
    if not scientific_name:
        return [], []
    common_names: list[str] = []
    scientific_names: list[str] = []
    try:
        match = request_with_retry("https://api.gbif.org/v1/species/match", params={"name": scientific_name})
        match.raise_for_status()
        payload = match.json()
        usage_key = payload.get("usageKey")
        for key in ("canonicalName", "species", "scientificName"):
            value = payload.get(key)
            if value:
                scientific_names.append(value)
        if not usage_key:
            return common_names, scientific_names

        vernacular = request_with_retry(f"https://api.gbif.org/v1/species/{usage_key}/vernacularNames")
        vernacular.raise_for_status()
        for row in vernacular.json().get("results", []):
            if str(row.get("language", "")).lower() in {"eng", "en", ""}:
                name = row.get("vernacularName")
                if name:
                    common_names.append(name)

        synonyms = request_with_retry(f"https://api.gbif.org/v1/species/{usage_key}/synonyms")
        synonyms.raise_for_status()
        for row in synonyms.json().get("results", []):
            name = row.get("canonicalName") or row.get("scientificName")
            if name:
                scientific_names.append(name)
    except requests.RequestException:
        pass
    return common_names, scientific_names


def wikidata_aliases(scientific_name: str) -> list[str]:
    """Return English labels/aliases for the Wikidata taxon matching this scientific name."""
    if not scientific_name:
        return []
    query = f"""
    SELECT ?itemLabel ?altLabel WHERE {{
      ?item wdt:P225 "{scientific_name}" .
      OPTIONAL {{ ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) IN ({', '.join(f'"{lang}"' for lang in WIKIDATA_LANGUAGES)})) }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{','.join(WIKIDATA_LANGUAGES)}". }}
    }}
    LIMIT 50
    """
    try:
        response = request_with_retry(
            "https://query.wikidata.org/sparql",
            params={"query": query, "format": "json"},
        )
        response.raise_for_status()
        bindings = response.json().get("results", {}).get("bindings", [])
    except (requests.RequestException, ValueError):
        return []
    out: list[str] = []
    for row in bindings:
        label = (row.get("itemLabel") or {}).get("value")
        alt = (row.get("altLabel") or {}).get("value")
        if label:
            out.append(label)
        if alt:
            out.append(alt)
    return out


def inaturalist_common_names(scientific_name: str) -> list[str]:
    if not scientific_name:
        return []
    try:
        response = request_with_retry(
            "https://api.inaturalist.org/v1/taxa",
            params={"q": scientific_name, "per_page": 5},
        )
        response.raise_for_status()
        results = response.json().get("results", [])
    except (requests.RequestException, ValueError):
        return []
    out: list[str] = []
    for result in results:
        preferred = result.get("preferred_common_name")
        if preferred:
            out.append(preferred)
        for name_entry in result.get("names", []) or []:
            if str(name_entry.get("locale", "")).startswith("en"):
                name = name_entry.get("name")
                if name:
                    out.append(name)
    return out


def harvest_for_plant(plant_id: str, name: str, scientific_name: str) -> list[str]:
    """Return a deduped list of newly-harvested alias candidates for one plant."""
    candidates: list[str] = []
    common, scientific_alts = gbif_aliases(scientific_name)
    candidates.extend(common)
    candidates.extend(scientific_alts)
    candidates.extend(wikidata_aliases(scientific_name))
    candidates.extend(inaturalist_common_names(scientific_name))

    seen_keys: set[str] = set()
    deduped: list[str] = []
    for alias in candidates:
        cleaned = clean_alias(alias)
        key = alias_key(cleaned)
        if not is_usable_alias(cleaned) or not key or key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(cleaned)
    return deduped


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Harvest only the first N catalogue plants")
    parser.add_argument("--plant-id", type=str, default=None, help="Harvest only this single plant id")
    parser.add_argument("--delay", type=float, default=0.4, help="Delay between plants (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing")
    parser.add_argument("--clean-only", action="store_true", help="Only strip aliases that fail is_usable_alias from the existing file; do not harvest new ones")
    args = parser.parse_args()

    if args.clean_only:
        synonyms = load_json(SYNONYMS_PATH, {"version": "1.0", "generated_at": None, "description": "Per-plant common-name aliases and synonym hints.", "plants": {}})
        removed_total = 0
        for plant_id, entry in synonyms.get("plants", {}).items():
            aliases = entry.get("aliases", [])
            filtered = [alias for alias in aliases if is_usable_alias(alias)]
            removed = len(aliases) - len(filtered)
            if removed:
                removed_total += removed
                print(f"{plant_id}: removed {removed} unusable alias(es)")
            entry["aliases"] = filtered
        if args.dry_run:
            print(f"\nDry run: would remove {removed_total} unusable aliases total. No files written.")
            return
        write_json(SYNONYMS_PATH, synonyms)
        print(f"\nRemoved {removed_total} unusable aliases from {SYNONYMS_PATH}")
        return

    catalogue = load_json(DOG_SAFE_PLANTS_PATH, {"plants": []})
    plants = catalogue.get("plants", [])
    if args.plant_id:
        plants = [item for item in plants if item.get("id") == args.plant_id]
        if not plants:
            print(f"No catalogue plant found with id '{args.plant_id}'.")
            return
    if args.limit is not None:
        plants = plants[: max(0, args.limit)]

    synonyms = load_json(SYNONYMS_PATH, {"version": "1.0", "generated_at": None, "description": "Per-plant common-name aliases and synonym hints.", "plants": {}})
    synonym_plants = synonyms.setdefault("plants", {})

    total_new = 0
    for number, plant in enumerate(plants, start=1):
        plant_id = str(plant.get("id", "")).strip()
        name = str(plant.get("name", "")).strip()
        scientific_name = str(plant.get("scientific_name", "")).strip()
        if not plant_id or not scientific_name or scientific_name.casefold() in {"not listed", "none listed", "n/a", "unknown"}:
            continue

        harvested = harvest_for_plant(plant_id, name, scientific_name)
        entry = synonym_plants.setdefault(plant_id, {"name": name, "scientific_name": scientific_name, "aliases": []})
        entry.setdefault("aliases", [])
        existing_keys = {alias_key(alias) for alias in entry["aliases"]}
        # Always make sure the canonical name/scientific name/id are present.
        for base_alias in (name, scientific_name, plant_id):
            key = alias_key(base_alias)
            if base_alias and key and key not in existing_keys:
                entry["aliases"].append(clean_alias(base_alias))
                existing_keys.add(key)

        new_aliases = []
        for alias in harvested:
            key = alias_key(alias)
            if key in existing_keys:
                continue
            if len(entry["aliases"]) >= MAX_ALIASES_PER_PLANT:
                break
            entry["aliases"].append(alias)
            existing_keys.add(key)
            new_aliases.append(alias)

        if new_aliases:
            total_new += len(new_aliases)
            print(f"[{number}/{len(plants)}] {name} ({plant_id}): +{len(new_aliases)} aliases -> {', '.join(new_aliases[:8])}{'...' if len(new_aliases) > 8 else ''}")
        else:
            print(f"[{number}/{len(plants)}] {name} ({plant_id}): no new aliases")

        if number < len(plants):
            time.sleep(args.delay)

    if args.dry_run:
        print(f"\nDry run: would add {total_new} new alias entries total. No files written.")
        return

    synonyms["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    write_json(SYNONYMS_PATH, synonyms)
    print(f"\nWrote {total_new} new alias entries to {SYNONYMS_PATH}")


if __name__ == "__main__":
    main()
