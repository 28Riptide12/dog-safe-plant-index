"""Fetch and stage plant candidates from external sources into import-ready JSON.

This script is intentionally review-first: it never mutates dog_safe_plants.json.
It writes:
  1) staged import payload (JSON with "plants" array)
  2) dedupe report (JSON)
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, SoupStrainer

BASE_DIR = Path(__file__).resolve().parents[1]
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
GENERATED_DIR = BASE_DIR / "data" / "generated-json"
DEFAULT_OUTPUT_PATH = GENERATED_DIR / "dog_safe_plants_ingest_candidates.json"
DEFAULT_REPORT_PATH = GENERATED_DIR / "dog_safe_plants_ingest_report.json"

SOURCE_TARGETS = [
    {
        "key": "aspca",
        "source_name": "ASPCA",
        "source_type": "veterinary-toxicology",
        "source_confidence": "high",
        "default_safety_status": "Toxic",
        "urls": [
            "https://www.aspca.org/pet-care/animal-poison-control/toxic-and-non-toxic-plants",
            "https://www.aspca.org/pet-care/animal-poison-control/toxic-and-non-toxic-plants?field_plant_family_value=All",
        ],
    },
    {
        "key": "petpoisonhelpline",
        "source_name": "Pet Poison Helpline",
        "source_type": "veterinary-toxicology",
        "source_confidence": "high",
        "default_safety_status": "Toxic",
        "urls": [
            "https://www.petpoisonhelpline.com/poisons/",
        ],
    },
    {
        "key": "vca",
        "source_name": "VCA Animal Hospitals",
        "source_type": "veterinary-toxicology",
        "source_confidence": "high",
        "default_safety_status": "Toxic",
        "urls": [
            "https://vcahospitals.com/know-your-pet",
        ],
    },
    {
        "key": "bluecross",
        "source_name": "Blue Cross",
        "source_type": "animal-welfare",
        "source_confidence": "medium",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://www.bluecross.org.uk/advice/dogs/garden-and-household-plants-that-are-toxic-to-dogs",
        ],
    },
    {
        "key": "pdsa",
        "source_name": "PDSA",
        "source_type": "animal-welfare",
        "source_confidence": "medium",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://www.pdsa.org.uk/pet-help-and-advice/looking-after-your-pet/poisoning-garden-plants",
        ],
    },
    {
        "key": "catsprotection",
        "source_name": "Cats Protection",
        "source_type": "animal-welfare",
        "source_confidence": "medium",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://www.cats.org.uk/help-and-advice/advice-and-articles/garden-and-household-plants-toxic-cats",
        ],
    },
    {
        "key": "rhs",
        "source_name": "RHS",
        "source_type": "horticulture",
        "source_confidence": "medium",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://www.rhs.org.uk/plants",
            "https://www.rhs.org.uk/plants/for-places",
        ],
    },
    {
        "key": "gardenersworld",
        "source_name": "Gardener's World",
        "source_type": "horticulture",
        "source_confidence": "medium",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://www.gardenersworld.com/plants/",
        ],
    },
    {
        "key": "university-extension",
        "source_name": "University extension pages",
        "source_type": "horticulture",
        "source_confidence": "medium",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://extension.psu.edu/plants-that-are-toxic-to-pets",
            "https://extension.umn.edu/yard-and-garden-insects/toxic-plants-dogs-cats",
            "https://extension.okstate.edu/fact-sheets/plants-toxic-to-dogs-and-cats.html",
        ],
    },
    {
        "key": "nursery-pet-safe",
        "source_name": "Nursery pet-safe notes",
        "source_type": "retail-horticulture",
        "source_confidence": "low",
        "default_safety_status": "May be Toxic",
        "urls": [
            "https://www.gardeners.com/buy/non-toxic-plant-list-for-dogs/",
            "https://www.rhs.org.uk/plants/for-places",
        ],
    },
]

SOURCE_DOMAIN_MAP = {
    "aspca": "aspca.org",
    "petpoisonhelpline": "petpoisonhelpline.com",
    "vca": "vcahospitals.com",
    "bluecross": "bluecross.org.uk",
    "pdsa": "pdsa.org.uk",
    "catsprotection": "cats.org.uk",
    "rhs": "rhs.org.uk",
    "gardenersworld": "gardenersworld.com",
    "university-extension": "extension.psu.edu",
    "nursery-pet-safe": "gardeners.com",
}

SCIENTIFIC_PATTERN = re.compile(
    r"\b([A-Z][a-z]{2,}(?:\s+[a-z][a-z-]{2,})(?:\s+(?:subsp\.|var\.|x)\s+[a-z-]{2,})?)\b"
)
COMMON_AND_SCI_PATTERN = re.compile(r"^\s*([A-Za-z][A-Za-z'’\-\s]{2,60})\s*\(([^)]+)\)\s*$")

STOPWORD_PHRASES = {
    "cookie policy",
    "privacy policy",
    "terms and conditions",
    "sign up",
    "read more",
    "learn more",
    "contact us",
    "poison control",
}
STOPWORD_PREFIXES = (
    "what ",
    "why ",
    "how ",
    "when ",
    "where ",
)
STOPWORD_WORDS = {
    "dogs",
    "cats",
    "pet",
    "poison",
    "toxic",
    "toxicity",
    "symptoms",
    "treatment",
    "emergency",
    "hospital",
    "support",
    "control",
}
COMMON_NAME_BLOCKLIST = {
    "get",
    "take",
    "join",
    "about",
    "activate",
    "campaign",
    "community",
    "gift",
    "membership",
    "action",
    "involved",
    "for",
    "place",
    "places",
    "garden",
    "gardening",
    "advice",
    "guide",
    "guides",
    "tool",
    "tools",
    "offer",
    "offers",
    "news",
    "event",
    "events",
    "profile",
    "help",
    "shop",
    "support",
}
KNOWN_GENERA: set[str] = set()


@dataclass
class Candidate:
    source_key: str
    source_name: str
    source_type: str
    source_confidence: str
    source_url: str
    default_safety_status: str
    name: str
    scientific_name: str


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "plant"


def canonical_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def scientific_key(value: Any) -> str:
    normalized = canonical_text(value)
    return "" if normalized in {"", "not listed", "none listed", "unknown", "n/a"} else normalized


def looks_like_scientific(value: str) -> bool:
    value = re.sub(r"\s+", " ", value).strip()
    if not SCIENTIFIC_PATTERN.fullmatch(value):
        return False
    genus = value.split(" ", 1)[0]
    if KNOWN_GENERA and genus not in KNOWN_GENERA:
        return False
    return True


def looks_like_common_name(value: str) -> bool:
    text = re.sub(r"\s+", " ", value).strip()
    lower = text.casefold()
    if len(text) < 3 or len(text) > 70:
        return False
    if any(char.isdigit() for char in text):
        return False
    if lower in STOPWORD_PHRASES or lower.startswith(STOPWORD_PREFIXES):
        return False
    words = [re.sub(r"[^a-z]", "", item.casefold()) for item in text.split()]
    words = [item for item in words if item]
    if not words:
        return False
    if len(words) > 6:
        return False
    if sum(1 for word in words if word in STOPWORD_WORDS) >= max(2, len(words) // 2 + 1):
        return False
    if len(words) <= 2 and any(word in COMMON_NAME_BLOCKLIST for word in words):
        return False
    return True


def clean_common_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" .,:;")


def clean_scientific_name(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip(" .,:;")
    if not text:
        return "Not listed"
    trailing = re.match(r"^([A-Z][a-z]{2,})\s+plants?$", text)
    if trailing:
        return trailing.group(1)
    if looks_like_scientific(text):
        return text
    return "Not listed"


def candidate_from_text(source: dict[str, str], source_url: str, name: str, scientific_name: str) -> Candidate | None:
    common = clean_common_name(name)
    scientific = clean_scientific_name(scientific_name)
    if not looks_like_common_name(common):
        return None
    return Candidate(
        source_key=source["key"],
        source_name=source["source_name"],
        source_type=source["source_type"],
        source_confidence=source["source_confidence"],
        source_url=source_url,
        default_safety_status=source["default_safety_status"],
        name=common,
        scientific_name=scientific,
    )


def extract_candidates_from_html(source: dict[str, Any], source_url: str, html: str) -> list[Candidate]:
    # Reduce parser load on very large pages by stripping script/style/comment blocks first.
    # This avoids long parser runs that can look like hangs in interactive terminals.
    cleaned_html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    cleaned_html = re.sub(r"<script\b[^>]*>.*?</script>", " ", cleaned_html, flags=re.S | re.I)
    cleaned_html = re.sub(r"<style\b[^>]*>.*?</style>", " ", cleaned_html, flags=re.S | re.I)
    cleaned_html = cleaned_html[:2_000_000]

    parse_only = SoupStrainer(["h1", "h2", "h3", "h4", "li"])
    soup = BeautifulSoup(cleaned_html, "html.parser", parse_only=parse_only)
    nodes = soup.select("h1, h2, h3, h4, li")
    candidates: list[Candidate] = []

    for node in nodes:
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True))
        if not text:
            continue
        match = COMMON_AND_SCI_PATTERN.match(text)
        if match and looks_like_scientific(match.group(2)):
            candidate = candidate_from_text(source, source_url, match.group(1), match.group(2))
            if candidate:
                candidates.append(candidate)
            continue

        for scientific in SCIENTIFIC_PATTERN.findall(text):
            if not looks_like_scientific(scientific):
                continue
            genus = scientific.split(" ", 1)[0]
            if not looks_like_common_name(genus):
                continue
            candidate = candidate_from_text(source, source_url, genus, scientific)
            if candidate:
                candidates.append(candidate)

    return candidates


def dedupe_candidates(
    existing: list[dict[str, Any]],
    candidates: list[Candidate],
    max_per_source: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    existing_name_keys = {canonical_text(item.get("name")) for item in existing}
    existing_scientific_keys = {scientific_key(item.get("scientific_name")) for item in existing}
    existing_id_keys = {canonical_text(item.get("id")) for item in existing}

    staged: list[dict[str, Any]] = []
    seen_name: set[str] = set()
    seen_scientific: set[str] = set()
    source_counts: dict[str, int] = {}
    skipped_existing = 0
    skipped_internal = 0

    for candidate in candidates:
        name_key = canonical_text(candidate.name)
        scientific_name = candidate.scientific_name
        scientific_name_key = scientific_key(scientific_name)
        base_id = slugify(f"{candidate.name}-{scientific_name if scientific_name != 'Not listed' else candidate.source_key}")
        if (
            name_key in existing_name_keys
            or (scientific_name_key and scientific_name_key in existing_scientific_keys)
            or base_id in existing_id_keys
        ):
            skipped_existing += 1
            continue
        if name_key in seen_name or (scientific_name_key and scientific_name_key in seen_scientific):
            skipped_internal += 1
            continue
        if source_counts.get(candidate.source_key, 0) >= max_per_source:
            skipped_internal += 1
            continue

        source_counts[candidate.source_key] = source_counts.get(candidate.source_key, 0) + 1
        seen_name.add(name_key)
        if scientific_name_key:
            seen_scientific.add(scientific_name_key)

        source_domain = SOURCE_DOMAIN_MAP.get(candidate.source_key) or urlparse(candidate.source_url).netloc.casefold()
        record = {
            "id": base_id,
            "name": candidate.name,
            "scientific_name": scientific_name,
            "category": "flowers",
            "safety_status": candidate.default_safety_status,
            "image_url": "",
            "description": (
                f"Staged from {candidate.source_name} for manual review. "
                "Confirm toxicity, source evidence, and category before import."
            ),
            "source_url": candidate.source_url,
            "source_status": f"Staged from {candidate.source_name}; requires review before merge.",
            "source_name": candidate.source_name,
            "source_type": candidate.source_type,
            "source_confidence": candidate.source_confidence,
            "source_domain": source_domain,
            "review_batch": "broader-source-candidates",
            "review_priority": "needs-evidence-check",
            "evidence_status": "pending",
            "image_status": "missing",
            "requires_image": True,
            "requires_description": True,
            "requires_source_validation": True,
            "audit_status": "pending",
            "audit_last_updated": None,
            "audit_history": [],
        }
        staged.append(record)

    report = {
        "staged_count": len(staged),
        "skipped_existing_count": skipped_existing,
        "skipped_internal_count": skipped_internal,
        "staged_by_source": source_counts,
    }
    return staged, report


def fetch_html(url: str, timeout: int) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; PlantIngestBot/1.0)"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.text


def run(output_path: Path, report_path: Path, timeout: int, max_per_source: int) -> None:
    existing_payload = json.loads(DOG_SAFE_PLANTS_PATH.read_text(encoding="utf-8"))
    existing_plants = existing_payload.get("plants", [])
    KNOWN_GENERA.clear()
    for plant in existing_plants:
        scientific = str(plant.get("scientific_name", "")).strip()
        if scientific and scientific.casefold() not in {"not listed", "none listed", "n/a", "unknown"}:
            genus = scientific.split(" ", 1)[0]
            if genus and genus[0].isupper():
                KNOWN_GENERA.add(genus)
    all_candidates: list[Candidate] = []
    source_reports: list[dict[str, Any]] = []

    for source in SOURCE_TARGETS:
        source_key = source["key"]
        source_report = {
            "source_key": source_key,
            "source_name": source["source_name"],
            "source_type": source["source_type"],
            "source_confidence": source["source_confidence"],
            "urls": source["urls"],
            "fetched": [],
            "fetch_errors": [],
            "raw_candidate_count": 0,
        }

        for url in source["urls"]:
            try:
                html = fetch_html(url, timeout=timeout)
            except requests.RequestException as error:
                source_report["fetch_errors"].append({"url": url, "error": str(error)})
                continue
            extracted = extract_candidates_from_html(source, url, html)
            all_candidates.extend(extracted)
            source_report["fetched"].append(url)
            source_report["raw_candidate_count"] += len(extracted)

        source_reports.append(source_report)

    staged, dedupe = dedupe_candidates(existing_plants, all_candidates, max_per_source=max_per_source)
    output_payload = {
        "source": "source-ingest-pipeline",
        "generated_at": now_iso(),
        "plants": staged,
    }
    report_payload = {
        "generated_at": now_iso(),
        "existing_count": len(existing_plants),
        "raw_candidate_count": len(all_candidates),
        **dedupe,
        "sources": source_reports,
        "output_file": str(output_path),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"Staged {len(staged)} candidate plant(s) -> {output_path}")
    print(f"Report written -> {report_path}")
    if dedupe["staged_by_source"]:
        print("Staged by source:", dedupe["staged_by_source"])
    else:
        print("No candidates staged. Check report fetch_errors for blocked sources.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage plant candidates from RHS/GW/PetPoison/VCA")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH), help="Path to staged import-ready JSON file.")
    parser.add_argument("--report", default=str(DEFAULT_REPORT_PATH), help="Path to dedupe/report JSON file.")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--max-per-source",
        type=int,
        default=120,
        help="Maximum staged candidates per source after dedupe.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_args()
    run(
        output_path=Path(arguments.output),
        report_path=Path(arguments.report),
        timeout=arguments.timeout,
        max_per_source=arguments.max_per_source,
    )
