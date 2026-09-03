"""Local Flask application for the Dog-Safe Garden Plants product."""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import requests
from flask import Flask, Response, jsonify, render_template, request, send_file

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "database"
BACKUP_DIR = BASE_DIR / "backups"
PLANT_IMAGE_CACHE_DIR = BASE_DIR / "plant_image_cache"
PLANT_USER_DB_PATH = BASE_DIR / "plant_user_data.db"


def data_file(name: str) -> Path:
    return DATA_DIR / name


def migrate_json_data_files() -> None:
    """Move runtime JSON files into database/ once, keeping startup backward-compatible."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    filenames = (
        "plant_library.json",
        "dog_safe_plants.json",
        "dog_safe_plants_scraped.json",
        "climate_zones.json",
        "plant_lifecycle_and_hardiness.json",
        "plant_toxicity_evidence.json",
        "plant_synonyms.json",
        "plant_colour_profiles.json",
        "plant_review_queue.json",
    )
    for name in filenames:
        legacy = BASE_DIR / name
        target = data_file(name)
        if legacy.exists() and not target.exists():
            legacy.replace(target)


PLANT_LIBRARY_PATH = data_file("plant_library.json")
DOG_SAFE_PLANTS_PATH = data_file("dog_safe_plants.json")
SCRAPED_DOG_SAFE_PLANTS_PATH = data_file("dog_safe_plants_scraped.json")
CLIMATE_ZONES_PATH = data_file("climate_zones.json")
PROFILE_OVERRIDES_PATH = BASE_DIR / "static" / "plant_profile_overrides.json"
LIFECYCLE_HARDINESS_PATH = data_file("plant_lifecycle_and_hardiness.json")
TOXICITY_EVIDENCE_PATH = data_file("plant_toxicity_evidence.json")
PLANT_SYNONYMS_PATH = data_file("plant_synonyms.json")
PLANT_COLOUR_PROFILES_PATH = data_file("plant_colour_profiles.json")
PLANT_REVIEW_QUEUE_PATH = data_file("plant_review_queue.json")

db_lock = threading.Lock()
app = Flask(__name__)
SOURCE_REGISTRY: dict[str, dict[str, str]] = {
    "aspca.org": {"source_name": "ASPCA", "source_type": "veterinary-toxicology", "source_confidence": "high"},
    "rhs.org.uk": {"source_name": "RHS", "source_type": "horticulture", "source_confidence": "medium"},
    "gardenersworld.com": {"source_name": "Gardener's World", "source_type": "horticulture", "source_confidence": "medium"},
    "petpoisonhelpline.com": {"source_name": "Pet Poison Helpline", "source_type": "veterinary-toxicology", "source_confidence": "high"},
    "vcahospitals.com": {"source_name": "VCA Animal Hospitals", "source_type": "veterinary-toxicology", "source_confidence": "high"},
    "cats.org.uk": {"source_name": "Cats Protection", "source_type": "animal-welfare", "source_confidence": "medium"},
    "bluecross.org.uk": {"source_name": "Blue Cross", "source_type": "animal-welfare", "source_confidence": "medium"},
    "pdsa.org.uk": {"source_name": "PDSA", "source_type": "animal-welfare", "source_confidence": "medium"},
    "purepetfood.com": {"source_name": "Pure Pet Food", "source_type": "pet-content", "source_confidence": "medium"},
    "oneclickplants.co.uk": {"source_name": "OneClickPlants", "source_type": "retail", "source_confidence": "medium"},
    "animalemergencyservice.com.au": {"source_name": "Animal Emergency Service", "source_type": "veterinary-toxicology", "source_confidence": "medium"},
}
SOURCE_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}

def init_plant_user_db():
    """Initialize the plant user database with tables if they don't exist."""
    import sqlite3
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
    cursor = conn.cursor()
    if app.config.get("TESTING"):
        for table_name in ["plant_timeline", "care_tasks", "user_plants", "plant_favorites"]:
            cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
    cursor.execute("""CREATE TABLE IF NOT EXISTS plant_favorites (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        plant_id TEXT NOT NULL,
        added_date TEXT DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, plant_id)
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS user_plants (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        plant_id TEXT NOT NULL,
        plant_name TEXT NOT NULL,
        location_name TEXT,
        planter_id TEXT,
        added_date TEXT NOT NULL,
        plant_notes TEXT,
        health_status TEXT DEFAULT 'good',
        last_photo_date TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS care_tasks (
        id TEXT PRIMARY KEY,
        user_plant_id TEXT NOT NULL,
        task_type TEXT NOT NULL,
        frequency_days INTEGER DEFAULT 7,
        last_done_date TEXT,
        next_due_date TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(user_plants)")}
    for name, definition in {
        "location_zone": "TEXT", "date_planted": "TEXT", "quantity_planted": "INTEGER DEFAULT 1", "source_nursery": "TEXT"
    }.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE user_plants ADD COLUMN {name} {definition}")
    cursor.execute("""CREATE TABLE IF NOT EXISTS plant_timeline (
        id TEXT PRIMARY KEY, user_plant_id TEXT NOT NULL, event_date TEXT NOT NULL,
        event_type TEXT NOT NULL, note TEXT, photo_url TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()


# Initialize the database on startup
migrate_json_data_files()
init_plant_user_db()

def write_json(path: Path, content: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(path)


class DuplicateKeyError(ValueError):
    """Raised when a JSON payload contains duplicate object keys."""


def json_loads_strict(raw_text: str, source_label: str = "JSON") -> Any:
    """Parse JSON while rejecting silently-overwritten duplicate keys."""
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise DuplicateKeyError(f"Duplicate key '{key}' found in {source_label}.")
            result[key] = value
        return result

    return json.loads(raw_text, object_pairs_hook=reject_duplicates)


def read_json_or(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json_loads_strict(path.read_text(encoding="utf-8"), str(path))
    except DuplicateKeyError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def clean_common_plant_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "")).strip()
    # Remove import collision suffixes like "Blue-dicks 2".
    cleaned = re.sub(r"\s+\d+$", "", cleaned).strip()
    return cleaned


def clean_scientific_plant_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "")).strip()
    if not cleaned:
        return cleaned
    if cleaned.casefold() in {"none listed", "n/a", "na", "unknown"}:
        return "Not listed"
    # Capitalize lowercase genus (e.g. "helianthus angustifolius" -> "Helianthus angustifolius")
    parts = cleaned.split(" ", 1)
    if parts and parts[0].islower():
        cleaned = f"{parts[0].capitalize()}{(' ' + parts[1]) if len(parts) > 1 else ''}"
    return cleaned


def infer_source_registry_meta(source_url: str) -> dict[str, str]:
    parsed = urlparse(str(source_url or "").strip())
    host = (parsed.netloc or "").casefold().strip()
    if host.startswith("www."):
        host = host[4:]
    for domain, meta in SOURCE_REGISTRY.items():
        if host == domain or host.endswith(f".{domain}"):
            return {"source_domain": domain, **meta}
    return {
        "source_domain": host or "",
        "source_name": host or "Unknown source",
        "source_type": "unclassified",
        "source_confidence": "low",
    }


def normalize_confidence(value: Any) -> str:
    key = str(value or "").strip().casefold()
    return key if key in SOURCE_CONFIDENCE_ORDER else "low"


def canonical_plant_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def canonical_plant_name_key(value: Any) -> str:
    cleaned = re.sub(r"\([^)]*\)", " ", canonical_plant_text(value))
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    alias_rewrites = {
        "aluminium": "aluminum",
        "aluminium plant": "aluminum plant",
        "banana plant": "banana",
    }
    cleaned = alias_rewrites.get(cleaned, cleaned)
    if cleaned.endswith("ies") and len(cleaned) > 4:
        cleaned = f"{cleaned[:-3]}y"
    elif cleaned.endswith("es") and len(cleaned) > 3:
        cleaned = cleaned[:-2]
    elif cleaned.endswith("s") and len(cleaned) > 3:
        cleaned = cleaned[:-1]
    # Normalize obvious generic suffix used by source-specific aliases.
    if cleaned in {"aluminum plant"}:
        cleaned = "aluminum"
    return cleaned


def scientific_key(value: Any) -> str:
    normalized = canonical_plant_text(value)
    return "" if normalized in {"", "not listed", "none listed", "n/a", "unknown"} else normalized


def plants_match(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_id = canonical_plant_text(left.get("id"))
    right_id = canonical_plant_text(right.get("id"))
    if left_id and right_id and left_id == right_id:
        return True
    left_name = canonical_plant_name_key(left.get("name"))
    right_name = canonical_plant_name_key(right.get("name"))
    if left_name and right_name and left_name == right_name:
        return True
    left_scientific = scientific_key(left.get("scientific_name"))
    right_scientific = scientific_key(right.get("scientific_name"))
    return bool(left_scientific and right_scientific and left_scientific == right_scientific)


def choose_preferred_plant(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    existing_confidence = normalize_confidence(existing.get("source_confidence"))
    candidate_confidence = normalize_confidence(candidate.get("source_confidence"))
    existing_score = SOURCE_CONFIDENCE_ORDER.get(existing_confidence, 0)
    candidate_score = SOURCE_CONFIDENCE_ORDER.get(candidate_confidence, 0)
    if candidate_score > existing_score:
        return candidate
    if existing_score > candidate_score:
        return existing
    if not str(existing.get("image_url", "")).strip() and str(candidate.get("image_url", "")).strip():
        return candidate
    return existing


def merge_plant_records(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if key in {"id", "name", "scientific_name", "category", "safety_status"}:
            continue
        if key == "indoor_outdoor":
            merged_tags = set(normalize_indoor_outdoor(merged.get("indoor_outdoor")))
            incoming_tags = set(normalize_indoor_outdoor(value))
            combined = [tag for tag in ("indoor", "outdoor") if tag in (merged_tags | incoming_tags)]
            if combined:
                merged["indoor_outdoor"] = combined
            continue
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
    preferred = choose_preferred_plant(merged, incoming)
    if preferred is incoming:
        merged.update({
            "source_url": incoming.get("source_url", merged.get("source_url", "")),
            "source_status": incoming.get("source_status", merged.get("source_status", "")),
            "source_type": incoming.get("source_type", merged.get("source_type", "")),
            "source_name": incoming.get("source_name", merged.get("source_name", "")),
            "source_confidence": incoming.get("source_confidence", merged.get("source_confidence", "low")),
            "source_domain": incoming.get("source_domain", merged.get("source_domain", "")),
        })
    return merged


def source_registry_enriched(plant: dict[str, Any]) -> dict[str, Any]:
    meta = infer_source_registry_meta(plant.get("source_url", ""))
    source_confidence = normalize_confidence(plant.get("source_confidence") or meta["source_confidence"])
    return {
        **plant,
        "source_domain": plant.get("source_domain") or meta["source_domain"],
        "source_name": plant.get("source_name") or meta["source_name"],
        "source_type": plant.get("source_type") or meta["source_type"],
        "source_confidence": source_confidence,
    }


def split_new_and_duplicates(existing: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    new_plants: list[dict[str, Any]] = []
    duplicates: list[dict[str, Any]] = []
    for candidate in candidates:
        if any(plants_match(candidate, row) for row in existing) or any(plants_match(candidate, row) for row in new_plants):
            duplicates.append(candidate)
        else:
            new_plants.append(candidate)
    return new_plants, duplicates


def image_url_is_placeholder(image_url: str) -> bool:
    lower_url = str(image_url or "").strip().casefold()
    if not lower_url:
        return True
    placeholder_tokens = (
        "placeholder",
        "default",
        "no-image",
        "example.com",
        "/static/placeholders/",
        "/static/plant-placeholder.svg",
        "/image_0.jpg",
        "aspca-logo-square.png",
    )
    return any(token in lower_url for token in placeholder_tokens)


def dedupe_plants_for_display(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return display rows without hiding alias entries.

    Keep every validated plant visible, but suffix repeated display names so
    common-name collisions don't collapse distinct catalogue entries.
    """
    seen_names: dict[str, int] = {}
    visible: list[dict[str, Any]] = []

    for row in rows:
        item = dict(row)
        common_name = canonical_plant_name_key(item.get("name"))
        scientific = scientific_key(item.get("scientific_name"))
        display_name = str(item.get("name", "")).strip()
        if not display_name:
            display_name = str(item.get("scientific_name", "")).strip() or str(item.get("id", "")).strip()

        if common_name:
            count = seen_names.get(common_name, 0)
            if count:
                suffix = str(item.get("scientific_name", "")).strip() or str(item.get("id", "")).strip()
                if suffix and suffix.casefold() not in display_name.casefold():
                    display_name = f"{display_name} ({suffix})"
                elif suffix:
                    display_name = f"{display_name} (entry {count + 1})"
            seen_names[common_name] = count + 1

        item["name"] = display_name
        visible.append(item)

    return visible


def normalize_indoor_outdoor(value: Any) -> list[str]:
    if value is None:
        return []
    raw_tokens: list[str] = []
    if isinstance(value, (list, tuple, set)):
        raw_tokens = [str(item) for item in value]
    else:
        raw_tokens = re.split(r"[,|/;]", str(value))

    normalized: list[str] = []
    for token in raw_tokens:
        text = token.strip().casefold()
        if not text:
            continue
        if "indoor" in text or "houseplant" in text or "house plant" in text:
            normalized.append("indoor")
        if "outdoor" in text or "garden" in text:
            normalized.append("outdoor")

    deduped: list[str] = []
    for item in normalized:
        if item not in deduped:
            deduped.append(item)
    return deduped


def infer_indoor_outdoor(plant: dict[str, Any]) -> list[str]:
    explicit = normalize_indoor_outdoor(plant.get("indoor_outdoor"))
    if explicit:
        return explicit

    text = " ".join(
        str(plant.get(field, ""))
        for field in ("name", "scientific_name", "description", "source_url")
    ).casefold()
    indoor_keywords = {
        "houseplant", "house plant", "indoor", "calathea", "pilea", "peperomia", "fittonia",
        "maranta", "hoya", "phalaenopsis", "spider plant", "string of turtles", "gasteria",
        "echeveria", "bromeliad", "chamaedorea", "asplenium", "davallia", "tillandsia",
        "chlorophytum", "anthericum comosum", "orchid", "fern", "palm", "succulent", "cactus",
        "radiator plant", "money tree", "prayer plant", "boston fern", "bird s nest fern",
        "areca palm", "lady palm", "ponytail palm", "ribbon plant", "spider ivy",
    }
    outdoor_keywords = {
        "garden", "outdoor", "border", "hedge", "bed", "tree", "shrub", "lawn", "meadow",
        "orchard", "vegetable", "herb", "fruit", "grassy",
    }

    tags: list[str] = []
    if any(keyword in text for keyword in indoor_keywords):
        tags.append("indoor")
    if any(keyword in text for keyword in outdoor_keywords):
        tags.append("outdoor")

    if not tags:
        tags = ["outdoor"]

    if "indoor" in tags and "outdoor" in tags:
        return ["indoor", "outdoor"]

@app.get("/plants")
def plants():
    return render_template("plants.html")


@app.get("/api/dog-safe-plants")
def dog_safe_plants():
    database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
    defaults = {"flowers": ("Upright", ["Full sun", "Partial shade"], "Well-draining, moist, loamy", "RHS H4", "Moderate", "Deadhead spent blooms"), "fruit": ("Spreading", ["Full sun"], "Rich, well-draining soil", "RHS H4", "Moderate", "Protect fruit from pests"), "vegetables": ("Clumping", ["Full sun"], "Fertile, moisture-retentive soil", "RHS H4", "Moderate", "Harvest regularly"), "herbs": ("Upright", ["Full sun", "Partial shade"], "Light, well-draining soil", "RHS H4", "Moderate", "Trim regularly for fresh growth"), "grasses": ("Clumping", ["Full sun", "Partial shade"], "Well-draining soil", "RHS H4", "Low", "Cut back in late winter")}
    enriched = []
    for plant in database.get("plants", []):
        item = dict(plant); habit, sun, soil, zone, watering, notes = defaults.get(item.get("category"), defaults["flowers"])
        original_name = str(item.get("name", "")).strip()
        cleaned_name = clean_common_plant_name(original_name)
        item["name"] = cleaned_name
        item["scientific_name"] = clean_scientific_plant_name(item.get("scientific_name", ""))
        if image_url_is_placeholder(item.get("image_url", "")):
            item["image_url"] = ""
        if cleaned_name and original_name and cleaned_name != original_name:
            description = str(item.get("description", ""))
            if description:
                item["description"] = description.replace(original_name, cleaned_name)
        item.setdefault("growth_habit", habit); item.setdefault("sun_exposure", sun); item.setdefault("soil_preference", soil); item.setdefault("hardiness_zone", zone); item.setdefault("mature_size", {"height_cm": None, "spread_cm": None}); item.setdefault("watering_needs", watering); item.setdefault("care_notes", notes); item["indoor_outdoor"] = infer_indoor_outdoor(item); enriched.append(source_registry_enriched(item))
    deduped = dedupe_plants_for_display(enriched)
    return jsonify({"source": database.get("source"), "plants": deduped})


def normalize_review_safety_status(value: Any) -> str:
    text = str(value or "").strip()
    lowered = text.casefold()
    if not lowered:
        return "Unknown"
    if "may be toxic" in lowered or "may-be-toxic" in lowered or "possible toxic" in lowered:
        return "May be Toxic"
    if "non-toxic" in lowered or "nontoxic" in lowered or "dog safe" in lowered or "safe" in lowered:
        return "Non-toxic"
    if "toxic" in lowered:
        return "Toxic"
    return text.title()


def append_review_queue_audit(queue_data: dict[str, Any], plant_id: str, plant_name: str, status: str, note: str = "") -> dict[str, Any]:
    audit_log = list(queue_data.setdefault("audit_log", []))
    entry = {
        "plant_id": plant_id,
        "plant_name": plant_name,
        "status": status,
        "performed_at": now_iso(),
        "note": note,
    }
    audit_log.append(entry)
    if len(audit_log) > 50:
        audit_log = audit_log[-50:]
    queue_data["audit_log"] = audit_log
    return queue_data


def append_review_item_audit(item: dict[str, Any], status: str, note: str = "") -> dict[str, Any]:
    history = item.get("audit_history")
    if not isinstance(history, list):
        history = []
    entry = {"status": status, "performed_at": now_iso(), "note": note}
    history.append(entry)
    if len(history) > 10:
        history = history[-10:]
    item["audit_status"] = status
    item["audit_last_updated"] = entry["performed_at"]
    item["audit_history"] = history
    return item


@app.get("/api/plant-review-queue")
def plant_review_queue():
    database = read_json_or(PLANT_REVIEW_QUEUE_PATH, {"plants": []})
    plants = []
    for plant in database.get("plants", []):
        item = dict(plant)
        item["safety_status"] = normalize_review_safety_status(item.get("safety_status"))
        item.setdefault("audit_status", "pending")
        history = item.get("audit_history")
        if not isinstance(history, list):
            item["audit_history"] = []
        plants.append(item)
    return jsonify({"source": database.get("source"), "generated_at": database.get("generated_at"), "audit_log": database.get("audit_log", []), "plants": plants})


@app.post("/api/plant-review-queue/<plant_id>/<action>")
def review_queue_action(plant_id: str, action: str):
    action = action.strip().lower()
    if action not in {"approve", "reject"}:
        return jsonify({"error": "Unsupported review action."}), 400

    queue_data = read_json_or(PLANT_REVIEW_QUEUE_PATH, {"plants": []})
    queue = list(queue_data.get("plants", []))
    target_index = None
    target = None
    for index, item in enumerate(queue):
        if str(item.get("id", "")) == plant_id:
            target_index = index
            target = item
            break

    if target is None:
        return jsonify({"error": "Review queue entry not found."}), 404

    if action == "reject":
        target = append_review_item_audit(dict(target), "rejected", "Rejected by curator")
        queue_data = append_review_queue_audit(queue_data, plant_id, str(target.get("name", plant_id)), "rejected", "Rejected by curator")
        queue.pop(target_index)
        write_json(PLANT_REVIEW_QUEUE_PATH, {**queue_data, "plants": queue})
        return jsonify({"status": "rejected", "plant_id": plant_id, "remaining": len(queue), "audit": target.get("audit_history", [])[-1:]})

    target = dict(target)
    target["safety_status"] = normalize_review_safety_status(target.get("safety_status"))
    safety_status = target.get("safety_status", "Unknown")

    note = "Approved into the live catalogue and tagged with its toxicity status." if safety_status in {"Toxic", "May be Toxic"} else "Approved into the live dog-safe catalogue."
    target = append_review_item_audit(target, "approved", note)
    queue_data = append_review_queue_audit(queue_data, plant_id, str(target.get("name", plant_id)), "approved", note)

    with db_lock:
        live_data = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
        live_plants = list(live_data.get("plants", []))
        plant_exists = any(str(item.get("id", "")) == str(target.get("id", "")) for item in live_plants)
        if not plant_exists:
            item = dict(target)
            item["name"] = clean_common_plant_name(item.get("name"))
            item["scientific_name"] = clean_scientific_plant_name(item.get("scientific_name", ""))
            if image_url_is_placeholder(item.get("image_url", "")):
                item["image_url"] = ""
            item.setdefault("category", "flowers")
            item.setdefault("growth_habit", "Upright")
            item.setdefault("sun_exposure", ["Full sun", "Partial shade"])
            item.setdefault("soil_preference", "Well-draining, moist, loamy")
            item.setdefault("hardiness_zone", "RHS H4")
            item.setdefault("mature_size", {"height_cm": None, "spread_cm": None})
            item.setdefault("watering_needs", "Moderate")
            item.setdefault("care_notes", "Deadhead spent blooms")
            item["indoor_outdoor"] = infer_indoor_outdoor(item)
            live_plants.append(source_registry_enriched(item))
            live_data["plants"] = live_plants
            write_json(DOG_SAFE_PLANTS_PATH, live_data)
        else:
            existing = next(item for item in live_plants if str(item.get("id", "")) == str(target.get("id", "")))
            existing["safety_status"] = safety_status
            existing["source_status"] = existing.get("source_status") or target.get("source_status")
            existing["audit_status"] = "approved"
            existing["audit_history"] = existing.get("audit_history", []) + [{"status": "approved", "performed_at": now_iso(), "note": note}]
            live_data["plants"] = live_plants
            write_json(DOG_SAFE_PLANTS_PATH, live_data)

        queue.pop(target_index)
        write_json(PLANT_REVIEW_QUEUE_PATH, {**queue_data, "plants": queue})

    return jsonify({"status": "approved", "plant_id": plant_id, "safety_status": safety_status, "remaining": len(queue), "audit": target.get("audit_history", [])[-1:]})


@app.get("/api/dog-safe-plants/needing-images")
def dog_safe_plants_needing_images():
    """Return plants that likely need images without slow network probing."""
    limit = max(1, min(int(request.args.get("limit", 600)), 2000))
    database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
    defaults = {
        "flowers": ("Upright", ["Full sun", "Partial shade"], "Well-draining, moist, loamy", "RHS H4", "Moderate", "Deadhead spent blooms"),
        "fruit": ("Spreading", ["Full sun"], "Rich, well-draining soil", "RHS H4", "Moderate", "Protect fruit from pests"),
        "vegetables": ("Clumping", ["Full sun"], "Fertile, moisture-retentive soil", "RHS H4", "Moderate", "Harvest regularly"),
        "herbs": ("Upright", ["Full sun", "Partial shade"], "Light, well-draining soil", "RHS H4", "Moderate", "Trim regularly for fresh growth"),
        "grasses": ("Clumping", ["Full sun", "Partial shade"], "Well-draining soil", "RHS H4", "Low", "Cut back in late winter"),
    }
    # Keep this list consistent with /api/dog-safe-plants by applying the same
    # name/scientific cleanup, inferred defaults, and display de-duplication.
    enriched: list[dict[str, Any]] = []
    for plant in database.get("plants", []):
        item = dict(plant)
        habit, sun, soil, zone, watering, notes = defaults.get(item.get("category"), defaults["flowers"])
        item["name"] = clean_common_plant_name(item.get("name"))
        item["scientific_name"] = clean_scientific_plant_name(item.get("scientific_name", ""))
        if image_url_is_placeholder(item.get("image_url", "")):
            item["image_url"] = ""
        item.setdefault("growth_habit", habit)
        item.setdefault("sun_exposure", sun)
        item.setdefault("soil_preference", soil)
        item.setdefault("hardiness_zone", zone)
        item.setdefault("mature_size", {"height_cm": None, "spread_cm": None})
        item.setdefault("watering_needs", watering)
        item.setdefault("care_notes", notes)
        item["indoor_outdoor"] = infer_indoor_outdoor(item)
        enriched.append(source_registry_enriched(item))

    visible_plants = dedupe_plants_for_display(enriched)
    plants_needing_images = []

    for plant in visible_plants:
        image_url = plant.get("image_url", "").strip()
        # Fast checks only: missing/invalid URLs and known placeholder-style values.
        if image_url_is_placeholder(image_url) or not image_url.startswith(("https://", "http://")):
            plants_needing_images.append(plant)

    return jsonify({
        "total": len(plants_needing_images),
        "limit": limit,
        "plants": plants_needing_images[:limit],
    })


@app.get("/api/dog-safe-plants/library")
def get_dog_safe_plant_library():
    return jsonify(read_json_or(PLANT_LIBRARY_PATH, {"favorite_ids": [], "care": {}}))


@app.put("/api/dog-safe-plants/library")
def update_dog_safe_plant_library():
    payload = request.get_json(force=True) or {}
    favorite_ids = payload.get("favorite_ids", [])
    care = payload.get("care", {})
    if not isinstance(favorite_ids, list) or not isinstance(care, dict):
        return jsonify({"error": "Library data must contain favorite_ids array and care object."}), 400
    known_ids = {plant.get("id") for plant in read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []}).get("plants", [])}
    if any(not isinstance(item, str) or item not in known_ids for item in favorite_ids):
        return jsonify({"error": "Library contains an unknown plant."}), 400
    library = {"favorite_ids": sorted(set(favorite_ids)), "care": {key: value for key, value in care.items() if key in known_ids and isinstance(value, dict)}}
    with db_lock:
        if PLANT_LIBRARY_PATH.exists():
            BACKUP_DIR.mkdir(exist_ok=True)
            shutil.copy2(PLANT_LIBRARY_PATH, BACKUP_DIR / f"plant-library-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
        write_json(PLANT_LIBRARY_PATH, library)
    return jsonify(library)


@app.get("/api/dog-safe-plants/merge-preview")
def dog_safe_plants_merge_preview():
    try:
        scraped = validate_dog_safe_plants(read_json_or(SCRAPED_DOG_SAFE_PLANTS_PATH, {"plants": []}))
    except (TypeError, ValueError) as error:
        return jsonify({"error": f"Scraped catalogue is invalid: {error}"}), 400
    current = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []}).get("plants", [])
    new_plants, duplicates = split_new_and_duplicates(current, scraped)
    return jsonify({"current": len(current), "scraped": len(scraped), "new": len(new_plants), "duplicates": len(scraped) - len(new_plants), "sample_new": [item["name"] for item in new_plants[:12]]})


@app.post("/api/dog-safe-plants/merge-scraped")
def merge_scraped_dog_safe_plants():
    try:
        scraped = validate_dog_safe_plants(read_json_or(SCRAPED_DOG_SAFE_PLANTS_PATH, {"plants": []}))
    except (TypeError, ValueError) as error:
        return jsonify({"error": f"Merge rejected; no plants were changed. {error}"}), 400
    with db_lock:
        database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
        current = [source_registry_enriched(item) for item in database.get("plants", [])]
        scraped = [source_registry_enriched(item) for item in scraped]
        new_plants, duplicates = split_new_and_duplicates(current, scraped)
        if not new_plants:
            return jsonify({"error": "Merge completed with no changes; all scraped plants already exist.", "imported": 0, "duplicates": len(scraped)}), 409
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(DOG_SAFE_PLANTS_PATH, BACKUP_DIR / f"dog-safe-plants-before-merge-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
        database["plants"] = current + new_plants
        write_json(DOG_SAFE_PLANTS_PATH, database)
    return jsonify({"imported": len(new_plants), "duplicates": len(scraped) - len(new_plants), "plants": new_plants}), 201


@app.get("/api/climate/zones")
def get_climate_zones():
    """Get UK climate zone data and postcode mappings."""
    climate_file = CLIMATE_ZONES_PATH
    if not climate_file.exists():
       return jsonify({"error": "Climate zone data not available."}), 404
    return jsonify(read_json_or(climate_file, {}))


@app.get("/api/climate/postcode/<postcode>")
def get_climate_for_postcode(postcode: str):
    """Get hardiness zone for a UK postcode."""
    postcode = postcode.upper().strip()
    climate_file = CLIMATE_ZONES_PATH
    
    if not climate_file.exists():
       return jsonify({"error": "Climate zone data not available."}), 404
    
    climate_data = read_json_or(climate_file, {})
    postcode_map = climate_data.get("postcode_map", {})
    
    # Try exact match first, then postcode area (first 1-2 letters)
    zone = postcode_map.get(postcode)
    if not zone:
       for length in [2, 1]:
           area = postcode[:length]
           zone = postcode_map.get(area)
           if zone:
               break

@app.get("/api/health/paths")
def get_health_paths():
    def describe(path: Path) -> dict[str, Any]:
        exists = path.exists()
        return {
            "path": str(path.resolve()),
            "exists": exists,
            "size_bytes": path.stat().st_size if exists else None,
        }

    return jsonify({
        "base_dir": str(BASE_DIR.resolve()),
        "database_dir": str(DATA_DIR.resolve()),
        "json_paths": {
            "plant_library": describe(PLANT_LIBRARY_PATH),
            "dog_safe_plants": describe(DOG_SAFE_PLANTS_PATH),
            "dog_safe_plants_scraped": describe(SCRAPED_DOG_SAFE_PLANTS_PATH),
            "climate_zones": describe(CLIMATE_ZONES_PATH),
            "plant_lifecycle_and_hardiness": describe(LIFECYCLE_HARDINESS_PATH),
            "plant_toxicity_evidence": describe(TOXICITY_EVIDENCE_PATH),
            "plant_synonyms": describe(PLANT_SYNONYMS_PATH),
            "plant_colour_profiles": describe(PLANT_COLOUR_PROFILES_PATH),
            "plant_review_queue": describe(PLANT_REVIEW_QUEUE_PATH),
            "profile_overrides": describe(PROFILE_OVERRIDES_PATH),
            "plant_user_db": describe(PLANT_USER_DB_PATH),
            "plant_image_cache": describe(PLANT_IMAGE_CACHE_DIR),
        },
    })


@app.get("/api/plant-lifecycle-hardiness")
def get_plant_lifecycle_hardiness():
    return jsonify(read_json_or(LIFECYCLE_HARDINESS_PATH, {"version": "1.0", "generated_at": None, "description": "Per-plant lifecycle and hardiness facts with provenance.", "plants": {}}))


@app.get("/api/plant-toxicity-evidence")
def get_plant_toxicity_evidence():
    return jsonify(read_json_or(TOXICITY_EVIDENCE_PATH, {"version": "1.0", "generated_at": None, "description": "Per-plant toxicity evidence records for dogs/cats with provenance and confidence.", "plants": {}}))


@app.get("/api/plant-synonyms")
def get_plant_synonyms():
    return jsonify(read_json_or(PLANT_SYNONYMS_PATH, {"version": "1.0", "generated_at": None, "description": "Per-plant common-name aliases and synonym hints.", "plants": {}}))


@app.get("/api/plant-colour-profiles")
def get_plant_colour_profiles():
    return jsonify(read_json_or(PLANT_COLOUR_PROFILES_PATH, {"version": "1.0", "generated_at": None, "description": "Per-plant colour palettes and alternate image variants for display.", "plants": {}}))


@app.get("/api/plants-by-climate")
def get_plants_by_climate():
    """Get plants suitable for a specific hardiness zone."""
    zone = request.args.get("zone", "").upper().strip()
    postcode = request.args.get("postcode", "").upper().strip()
    limit = int(request.args.get("limit", 600))
    
    # Resolve postcode to zone if postcode is provided
    if postcode and not zone:
       climate_file = CLIMATE_ZONES_PATH
       if climate_file.exists():
           climate_data = read_json_or(climate_file, {})
           postcode_map = climate_data.get("postcode_map", {})
            
           for length in [len(postcode), 2, 1]:
               area = postcode[:length]
               zone = postcode_map.get(area)
               if zone:
                   break
    
    if not zone:
       return jsonify({"error": "Provide either 'zone' (e.g., H4) or 'postcode' parameter."}), 400
    
    database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
    plants = database.get("plants", [])
    
    # Filter plants by hardiness zone compatibility
    suitable = []
    for plant in plants:
       plant_zones = plant.get("hardiness_zones_uk", "").split("-")
       # Check if plant's hardiness zone matches user's zone
       # A plant is suitable if user's zone is within its range or overlaps
       if any(plant_zones) and zone:
           # Simple matching: if user zone is mentioned in plant zones or overlaps
           if zone in plant_zones or any(z == zone for z in plant_zones):
               suitable.append(plant)
           # Also include plants with broader ranges (e.g., "H2-H7" includes "H4")
           elif "-" in plant.get("hardiness_zones_uk", ""):
               parts = plant.get("hardiness_zones_uk", "").split("-")
               if len(parts) == 2:
                   min_zone, max_zone = parts
                   # Extract zone number for comparison (e.g., "H4" -> 4)
                   try:
                       user_num = int(zone.replace("H", ""))
                       min_num = int(min_zone.replace("H", ""))
                       max_num = int(max_zone.replace("H", ""))
                       if min_num <= user_num <= max_num:
                           suitable.append(plant)
                   except (ValueError, AttributeError):
                       suitable.append(plant)  # Include if parsing fails
    
    return jsonify({
       "climate_zone": zone,
       "postcode": postcode,
       "total_plants": len(plants),
       "suitable_count": len(suitable),
       "plants": suitable[:limit]
    })


@app.get("/api/plant-image")
def plant_image():
    image_url = request.args.get("url", "").strip()
    if not image_url:
        return jsonify({"error": "No image URL provided"}), 400
    
    parsed = urlparse(image_url)
    allowed_hosts = {
        "upload.wikimedia.org",
        "commons.wikimedia.org",
        "www.aspca.org",
        "images.unsplash.com",
        "images.pexels.com",
        "inaturalist-open-data.s3.amazonaws.com",
        "static.inaturalist.org",
    }
    
    if parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in allowed_hosts:
        return jsonify({"error": "Image host is not allowed"}), 400
    
    try:
        # Try original URL first
        response = requests.get(image_url, headers={"User-Agent": "TopsoilPlantGuide/1.0"}, timeout=15, stream=True)
        
        # If original fails, try Wikimedia fallback for Wikimedia URLs
        if response.status_code >= 400 and parsed.hostname in {"upload.wikimedia.org", "commons.wikimedia.org"}:
            response.close()
            filename = unquote(parsed.path.rsplit("/", 1)[-1])
            fallback_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{quote(filename)}"
            response = requests.get(fallback_url, headers={"User-Agent": "TopsoilPlantGuide/1.0"}, timeout=15, stream=True)
        
        response.raise_for_status()
        
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        if not content_type.startswith("image/"):
            content_type = "image/jpeg"
        
        # Stream response directly without caching to avoid stale cache issues
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return Response(generate(), content_type=content_type, headers={
            "Cache-Control": "public, max-age=3600",
            "Content-Type": content_type,
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type"
        })
    
    except (requests.RequestException, OSError, ValueError) as e:
        app.logger.error(f"Image proxy error for {image_url}: {e}")
        return jsonify({"error": f"Could not load image: {str(e)[:100]}"}), 502


@app.get("/api/plant-local-image")
def plant_local_image():
    file_name = request.args.get("file", "")
    if not re.fullmatch(r"[A-Za-z0-9._ -]+", file_name) or Path(file_name).name != file_name:
        return jsonify({"error": "Invalid local image name."}), 400
    image_path = PLANT_IMAGE_CACHE_DIR / file_name
    if not image_path.is_file():
        return jsonify({"error": "Local image not found."}), 404
    return send_file(image_path, max_age=86400)


@app.get("/api/dog-safe-plants/photo-suggestion")
def dog_safe_plant_photo_suggestion():
    name = str(request.args.get("name", "")).strip()
    scientific_name = str(request.args.get("scientific_name", "")).strip()
    if not name and not scientific_name:
        return jsonify({"error": "Plant name or scientific name is required."}), 400

    def normalize_scientific_phrase(value: str) -> str:
        cleaned = clean_scientific_plant_name(value)
        cleaned = re.sub(r"[^A-Za-z0-9.\- ]+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if not cleaned:
            return ""
        token_corrections = {
            "aregelia": "neoregelia",
            "neoregalia": "neoregelia",
            "plantanus": "platanus",
        }
        corrected = cleaned.casefold()
        for wrong, right in token_corrections.items():
            corrected = re.sub(rf"\b{re.escape(wrong)}\b", right, corrected)
        return corrected

    def reduced_scientific_tokens(value: str) -> list[str]:
        ignore = {"spp", "spp.", "sp", "sp.", "species", "var", "var.", "cv", "cv.", "cultivar", "x"}
        tokens = [token.casefold() for token in re.findall(r"[a-z]+", value) if len(token) > 1]
        return [token for token in tokens if token not in ignore]

    def commons_query(search_term: str) -> list[dict[str, Any]]:
        if not search_term:
            return []
        result = requests.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "generator": "search",
                "gsrsearch": search_term,
                "gsrnamespace": 6,
                "gsrlimit": 10,
                "prop": "imageinfo|pageprops",
                "iiprop": "url",
                "iiurlwidth": 900,
                "ppprop": "wikibase_item",
                "format": "json",
            },
            headers={"User-Agent": "TopsoilPlantGuide/1.0"},
            timeout=15,
        )
        result.raise_for_status()
        pages = result.json().get("query", {}).get("pages", {}).values()
        return [page for page in pages if page.get("imageinfo")]

    def openverse_query(search_term: str) -> list[dict[str, Any]]:
        if not search_term:
            return []
        result = requests.get(
            "https://api.openverse.org/v1/images/",
            params={
                "q": search_term,
                "page_size": 8,
                "license_type": "all-cc",
                "page": 1,
            },
            headers={"User-Agent": "TopsoilPlantGuide/1.0"},
            timeout=15,
        )
        result.raise_for_status()
        content_type = (result.headers.get("Content-Type", "") or "").lower()
        if "application/json" not in content_type and "json" not in content_type:
            preview = re.sub(r"\s+", " ", result.text or "")[:180]
            raise ValueError(f"Openverse API returned non-JSON content for '{search_term}': {preview}")
        payload = result.json()
        return [
            item for item in payload.get("results", [])
            if str(item.get("url") or item.get("thumbnail") or "").startswith("https://")
        ]

    scientific_variants: list[str] = []
    if scientific_name:
        scientific_variants.append(normalize_scientific_phrase(scientific_name))
        scientific_variants.extend(normalize_scientific_phrase(match) for match in re.findall(r"\(([^)]*)\)", scientific_name))
    scientific_variants = [item for item in scientific_variants if item]
    primary_scientific = scientific_variants[0] if scientific_variants else normalize_scientific_phrase(name)
    scientific_tokens = reduced_scientific_tokens(primary_scientific)
    expected_genus = scientific_tokens[0] if scientific_tokens else ""
    expected_species = f"{scientific_tokens[0]} {scientific_tokens[1]}" if len(scientific_tokens) >= 2 else ""
    confidence_order = {"low": 0, "medium": 1, "high": 2}
    low_quality_title_pattern = re.compile(
        r"\b(herbarium|specimen|pressed|dried|withered|wilt(?:ed|ing)?|senescent|necros(?:is|ed)|diseased?|dead)\b|brown(?:ed)?\s+leaves?",
        re.IGNORECASE,
    )

    def infer_confidence_from_taxon_name(taxon_name: str) -> str:
        normalized = canonical_plant_text(taxon_name)
        if expected_species and expected_species in normalized:
            return "high"
        if expected_genus and expected_genus in normalized:
            return "medium"
        return "low"

    def add_candidate(
        candidate_map: dict[str, dict[str, Any]],
        image_url: str,
        source_url: str,
        title: str,
        source_name: str,
        confidence: str,
        match_type: str,
    ) -> None:
        image_url = str(image_url or "").strip()
        source_url = str(source_url or "").strip()
        title = str(title or "").strip()
        if not image_url.startswith("https://") or not source_url.startswith("https://"):
            return
        candidate_text = f"{title} {source_url} {image_url}"
        if low_quality_title_pattern.search(candidate_text):
            return
        key = image_url
        candidate = {
            "title": title or "Plant image",
            "image_url": image_url,
            "source_url": source_url,
            "source_name": source_name,
            "confidence": confidence,
            "match_type": match_type,
            "manual_review_required": confidence == "low",
        }
        current = candidate_map.get(key)
        if not current or confidence_order.get(confidence, 0) > confidence_order.get(str(current.get("confidence", "low")), 0):
            candidate_map[key] = candidate

    def wikidata_depicts_confidence(wikibase_item: str) -> tuple[str, str]:
        if not wikibase_item:
            return ("low", "")
        entity_response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={"action": "wbgetentities", "ids": wikibase_item, "props": "claims", "format": "json"},
            headers={"User-Agent": "TopsoilPlantGuide/1.0"},
            timeout=15,
        )
        entity_response.raise_for_status()
        entities = entity_response.json().get("entities", {})
        entity = entities.get(wikibase_item, {})
        depicts_claims = entity.get("claims", {}).get("P180", [])
        depicted_ids = []
        for claim in depicts_claims:
            value = (((claim or {}).get("mainsnak") or {}).get("datavalue") or {}).get("value", {})
            item_id = value.get("id")
            if isinstance(item_id, str) and item_id:
                depicted_ids.append(item_id)
        if not depicted_ids:
            return ("low", "")
        depicted_response = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={"action": "wbgetentities", "ids": "|".join(depicted_ids[:25]), "props": "labels|claims", "languages": "en", "format": "json"},
            headers={"User-Agent": "TopsoilPlantGuide/1.0"},
            timeout=15,
        )
        depicted_response.raise_for_status()
        depicted_entities = depicted_response.json().get("entities", {})
        best = ("low", "")
        for entity_data in depicted_entities.values():
            labels = entity_data.get("labels", {})
            label = ((labels.get("en") or {}).get("value") or "").strip()
            p225_claims = entity_data.get("claims", {}).get("P225", [])
            scientific_values = []
            for claim in p225_claims:
                val = (((claim or {}).get("mainsnak") or {}).get("datavalue") or {}).get("value")
                if isinstance(val, str):
                    scientific_values.append(val)
            names = [label, *scientific_values]
            for taxon_name in names:
                confidence = infer_confidence_from_taxon_name(taxon_name)
                if confidence_order[confidence] > confidence_order[best[0]]:
                    best = (confidence, taxon_name)
        return best

    search_terms: list[str] = []
    for variant in scientific_variants:
        if variant not in search_terms:
            search_terms.append(variant)
        tokens = reduced_scientific_tokens(variant)
        if len(tokens) >= 2:
            phrase = f"{tokens[0]} {tokens[1]}"
            if phrase not in search_terms:
                search_terms.append(phrase)
        if tokens:
            genus = tokens[0]
            if genus not in search_terms:
                search_terms.append(genus)
    if name and name not in search_terms:
        search_terms.append(name)

    try:
        candidates_map: dict[str, dict[str, Any]] = {}

        # 1) iNaturalist taxon-id-first (high/medium confidence from matched taxon).
        if primary_scientific:
            taxa_response = requests.get(
                "https://api.inaturalist.org/v1/taxa/autocomplete",
                params={"q": primary_scientific, "per_page": 8},
                headers={"User-Agent": "TopsoilPlantGuide/1.0"},
                timeout=15,
            )
            taxa_response.raise_for_status()
            taxa = taxa_response.json().get("results", [])
            matched_taxa = []
            for taxon in taxa:
                taxon_name = str(taxon.get("name", "")).strip()
                confidence = infer_confidence_from_taxon_name(taxon_name)
                if confidence in {"high", "medium"}:
                    matched_taxa.append((taxon, confidence))
            for taxon, confidence in matched_taxa[:3]:
                taxon_id = taxon.get("id")
                if not taxon_id:
                    continue
                obs_response = requests.get(
                    "https://api.inaturalist.org/v1/observations",
                    params={"taxon_id": taxon_id, "photos": "true", "quality_grade": "research", "order_by": "votes", "per_page": 5},
                    headers={"User-Agent": "TopsoilPlantGuide/1.0"},
                    timeout=15,
                )
                obs_response.raise_for_status()
                for obs in obs_response.json().get("results", []):
                    obs_id = obs.get("id")
                    source_url = f"https://www.inaturalist.org/observations/{obs_id}" if obs_id else "https://www.inaturalist.org/"
                    for photo in obs.get("photos", [])[:2]:
                        image_url = str(photo.get("large_url") or photo.get("url") or "").strip()
                        if "/square." in image_url:
                            image_url = image_url.replace("/square.", "/large.")
                        add_candidate(
                            candidates_map,
                            image_url=image_url,
                            source_url=source_url,
                            title=f"iNaturalist · {taxon.get('name', 'Taxon')}",
                            source_name="iNaturalist",
                            confidence=confidence,
                            match_type="taxon-id",
                        )

        # 2) GBIF taxon-id-first (high/medium confidence from matched usage key).
        if primary_scientific:
            gbif_match_response = requests.get(
                "https://api.gbif.org/v1/species/match",
                params={"name": primary_scientific, "strict": "false"},
                headers={"User-Agent": "TopsoilPlantGuide/1.0"},
                timeout=15,
            )
            gbif_match_response.raise_for_status()
            gbif_match = gbif_match_response.json()
            usage_key = gbif_match.get("usageKey")
            if usage_key:
                gbif_name = str(gbif_match.get("scientificName") or gbif_match.get("canonicalName") or "").strip()
                gbif_confidence = infer_confidence_from_taxon_name(gbif_name)
                if gbif_confidence in {"high", "medium"}:
                    gbif_occ_response = requests.get(
                        "https://api.gbif.org/v1/occurrence/search",
                        params={"taxonKey": usage_key, "mediaType": "StillImage", "limit": 8},
                        headers={"User-Agent": "TopsoilPlantGuide/1.0"},
                        timeout=15,
                    )
                    gbif_occ_response.raise_for_status()
                    for occ in gbif_occ_response.json().get("results", []):
                        for media in (occ.get("media") or [])[:2]:
                            image_url = str(media.get("identifier") or "").strip()
                            occ_key = str(occ.get("key") or "").strip()
                            source_url = f"https://www.gbif.org/occurrence/{occ_key}" if occ_key else "https://www.gbif.org/"
                            add_candidate(
                                candidates_map,
                                image_url=image_url,
                                source_url=source_url,
                                title=f"GBIF · {gbif_name or primary_scientific}",
                                source_name="GBIF",
                                confidence=gbif_confidence,
                                match_type="taxon-id",
                            )

        # 3) Wikimedia Commons (Wikidata-linked first; low-confidence filename fallback).
        pages_by_title: dict[str, dict[str, Any]] = {}
        for term in search_terms:
            for page in commons_query(term):
                title = str(page.get("title", "")).strip()
                if title and title not in pages_by_title:
                    pages_by_title[title] = page

        name_tokens = [token.casefold() for token in re.findall(r"[a-z]+", name) if len(token) > 2]
        matches = []
        for page in pages_by_title.values():
            title = page.get("title", "").casefold()
            scientific_hits = sum(1 for token in scientific_tokens if token in title)
            name_hits = sum(1 for token in name_tokens if token in title)
            if scientific_hits >= 1 or name_hits >= 2:
                matches.append((scientific_hits, name_hits, page))
        matches.sort(key=lambda item: (item[0], item[1]), reverse=True)
        for _, _, match in matches[:8]:
            info = match["imageinfo"][0]
            image_url = info.get("thumburl") or info.get("url")
            source_url = info.get("descriptionurl") or f"https://commons.wikimedia.org/wiki/{quote(match.get('title', '').replace(' ', '_'))}"
            wikibase_item = (((match or {}).get("pageprops") or {}).get("wikibase_item") or "").strip()
            confidence = "low"
            matched_taxon = ""
            if wikibase_item:
                confidence, matched_taxon = wikidata_depicts_confidence(wikibase_item)
            if confidence == "low":
                # Filename/text-only fallback remains available but flagged for manual review.
                title_text = str(match.get("title", ""))
                confidence = infer_confidence_from_taxon_name(title_text)
                if confidence == "high":
                    confidence = "medium"
            add_candidate(
                candidates_map,
                image_url=image_url,
                source_url=source_url,
                title=f"{match.get('title', '')}{f' · {matched_taxon}' if matched_taxon else ''}",
                source_name="Wikimedia Commons",
                confidence=confidence,
                match_type="wikidata-linked" if wikibase_item else "filename-text",
            )

        # 4) Openverse (good fallback when Commons/GBIF/iNat are sparse or the plant is more catalogued in general CC stock libraries).
        for term in search_terms:
            for result in openverse_query(term):
                image_url = str(result.get("url") or result.get("thumbnail") or "").strip()
                source_url = str(result.get("foreign_landing_url") or result.get("source") or result.get("detail_url") or "https://openverse.org/").strip()
                if not source_url.startswith("https://"):
                    source_url = "https://openverse.org/"
                title = str(result.get("title") or "Openverse image").strip()
                confidence = infer_confidence_from_taxon_name(title)
                if confidence == "low":
                    confidence = infer_confidence_from_taxon_name(primary_scientific)
                add_candidate(
                    candidates_map,
                    image_url=image_url,
                    source_url=source_url,
                    title=title,
                    source_name="Openverse",
                    confidence=confidence,
                    match_type="openverse-search",
                )

        if not candidates_map:
            label = name or "this plant"
            scientific_label = scientific_name or "no scientific name provided"
            return jsonify({"error": f"No confident photo match found for {label} ({scientific_label})."}), 404

        candidates = sorted(
            candidates_map.values(),
            key=lambda item: (confidence_order.get(str(item.get("confidence", "low")), 0), str(item.get("source_name", ""))),
            reverse=True,
        )[:8]
        summary = {
            "high": sum(1 for candidate in candidates if candidate.get("confidence") == "high"),
            "medium": sum(1 for candidate in candidates if candidate.get("confidence") == "medium"),
            "low": sum(1 for candidate in candidates if candidate.get("confidence") == "low"),
        }
        return jsonify({"name": name, "scientific_name": scientific_name, "candidates": candidates, "confidence_summary": summary, **candidates[0]})
    except (requests.RequestException, ValueError, KeyError) as error:
        return jsonify({"error": f"Photo search failed: {error}"}), 502


@app.post("/api/dog-safe-plants/<plant_id>/photo")
def save_dog_safe_plant_photo(plant_id: str):
    payload = request.get_json(force=True) or {}
    image_url = str(payload.get("image_url", "")).strip()
    image_source_url = str(payload.get("image_source_url", "")).strip()
    source_host = (urlparse(image_source_url).netloc or "").casefold().strip(".")
    allowed_host_roots = {
        "commons.wikimedia.org",
        "wikidata.org",
        "inaturalist.org",
        "gbif.org",
        "rhs.org.uk",
        "powo.science.kew.org",
        "science.kew.org",
        "missouribotanicalgarden.org",
        "openverse.org",
        "flickr.com",
        "staticflickr.com",
    }

    def is_approved_source_host(host: str) -> bool:
        compact = host.casefold().strip(".")
        if compact.startswith("www."):
            compact = compact[4:]
        return any(compact == root or compact.endswith(f".{root}") for root in allowed_host_roots)

    if not image_url.startswith("https://") or not image_source_url.startswith("https://") or not is_approved_source_host(source_host):
        return jsonify({"error": "Only HTTPS images from approved plant-reference sources can be saved."}), 400
    with db_lock:
        database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
        plant = next((item for item in database["plants"] if item.get("id") == plant_id), None)
        if not plant:
            return jsonify({"error": "Plant not found."}), 404
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(DOG_SAFE_PLANTS_PATH, BACKUP_DIR / f"dog-safe-plants-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
        plant["image_url"] = image_url
        plant["image_source_url"] = image_source_url
        write_json(DOG_SAFE_PLANTS_PATH, database)
    return jsonify(plant)


@app.put("/api/dog-safe-plants/<plant_id>/image-framing")
def update_dog_safe_plant_image_framing(plant_id: str):
    payload = request.get_json(force=True) or {}
    object_position = str(payload.get("image_object_position", "")).strip().lower()
    allowed_positions = {
        "center center",
        "top center",
        "bottom center",
        "center left",
        "center right",
        "top left",
        "top right",
        "bottom left",
        "bottom right",
    }
    if object_position not in allowed_positions:
        return jsonify({"error": "Invalid image_object_position value."}), 400
    with db_lock:
        database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
        plant = next((item for item in database["plants"] if item.get("id") == plant_id), None)
        if not plant:
            return jsonify({"error": "Plant not found."}), 404
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(DOG_SAFE_PLANTS_PATH, BACKUP_DIR / f"dog-safe-plants-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
        plant["image_object_position"] = object_position
        write_json(DOG_SAFE_PLANTS_PATH, database)
    return jsonify({"id": plant_id, "image_object_position": object_position})


def validate_dog_safe_plants(parsed: Any) -> list[dict[str, Any]]:
    rows = parsed.get("plants", parsed) if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise ValueError("JSON must contain a plants array.")
    categories = {"flowers", "fruit", "vegetables", "herbs", "grasses"}
    required = {"id", "name", "scientific_name", "category", "safety_status", "image_url", "description", "source_url"}
    validated = []
    seen = set()
    safety_map = {
        "non-toxic to dogs": "Non-toxic to dogs",
        "nontoxic to dogs": "Non-toxic to dogs",
        "may be toxic": "May be Toxic",
        "toxic": "Toxic",
    }
    for row_number, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise ValueError(f"Plant {row_number} must be an object.")
        missing = sorted(required - set(row))
        if missing:
            raise ValueError(f"Plant {row_number} is missing: {', '.join(missing)}.")
        plant = {key: str(row[key]).strip() for key in required}
        if not plant["id"] or not plant["name"] or not plant["scientific_name"]:
            raise ValueError(f"Plant {row_number} must have an id, name, and scientific_name.")
        if plant["category"] not in categories:
            raise ValueError(f"Plant {row_number} has an invalid category.")
        safety_key = re.sub(r"\s+", " ", plant["safety_status"]).strip().casefold()
        if safety_key not in safety_map:
            raise ValueError(f"Plant {row_number} has an invalid safety_status (use Non-toxic to dogs, May be Toxic, or Toxic).")
        plant["safety_status"] = safety_map[safety_key]
        if not re.match(r"^https://", plant["source_url"], re.I):
            raise ValueError(f"Plant {row_number} must include an HTTPS source_url.")
        indoor_outdoor = normalize_indoor_outdoor(row.get("indoor_outdoor"))
        if row.get("indoor_outdoor") is not None and not indoor_outdoor:
            raise ValueError(f"Plant {row_number} has an invalid indoor_outdoor value (use indoor, outdoor, or both).")
        if indoor_outdoor:
            plant["indoor_outdoor"] = indoor_outdoor
        if "source_status" in row and str(row.get("source_status", "")).strip():
            plant["source_status"] = str(row["source_status"]).strip()
        if "toxicity_details" in row and str(row.get("toxicity_details", "")).strip():
            plant["toxicity_details"] = str(row["toxicity_details"]).strip()
        if "source_confidence" in row and str(row.get("source_confidence", "")).strip():
            confidence = normalize_confidence(row.get("source_confidence"))
            if confidence not in SOURCE_CONFIDENCE_ORDER:
                raise ValueError(f"Plant {row_number} has invalid source_confidence (use high, medium, or low).")
            plant["source_confidence"] = confidence
        if "source_type" in row and str(row.get("source_type", "")).strip():
            plant["source_type"] = str(row["source_type"]).strip()
        if "source_name" in row and str(row.get("source_name", "")).strip():
            plant["source_name"] = str(row["source_name"]).strip()
        plant = source_registry_enriched(plant)
        if plant["id"].casefold() in seen:
            raise ValueError(f"Duplicate plant id in file: {plant['id']}.")
        seen.add(plant["id"].casefold())
        validated.append(plant)
    return validated


@app.post("/api/dog-safe-plants/import")
def import_dog_safe_plants():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename.lower().endswith(".json"):
        return jsonify({"error": "Choose a JSON plant file."}), 400
    try:
        payload = json_loads_strict(uploaded.read().decode("utf-8-sig"), uploaded.filename)
        plants = validate_dog_safe_plants(payload)
    except (UnicodeDecodeError, DuplicateKeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return jsonify({"error": f"Import rejected; no plants were changed. {error}"}), 400
    with db_lock:
        database = read_json_or(DOG_SAFE_PLANTS_PATH, {"plants": []})
        existing = [source_registry_enriched(item) for item in database.get("plants", [])]
        plants = [source_registry_enriched(item) for item in plants]
        new_plants, duplicates = split_new_and_duplicates(existing, plants)
        skipped = [plant["name"] for plant in duplicates]
        if new_plants:
            BACKUP_DIR.mkdir(exist_ok=True)
            if DOG_SAFE_PLANTS_PATH.exists():
                shutil.copy2(DOG_SAFE_PLANTS_PATH, BACKUP_DIR / f"dog-safe-plants-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
            database["plants"] = existing + new_plants
            write_json(DOG_SAFE_PLANTS_PATH, database)
    return jsonify({"imported": len(new_plants), "skipped": skipped, "plants": new_plants}), 201 if new_plants else 409


# ============= PLANT FAVORITES API =============
@app.get("/api/plant-favorites")
def get_plant_favorites():
    """Get all favorite plants for a user."""
    user_id = request.args.get("user_id", "default")
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, user_id, plant_id, added_date FROM plant_favorites WHERE user_id = ? ORDER BY added_date DESC", (user_id,))
    favorites = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"user_id": user_id, "favorites": favorites})


@app.post("/api/plant-favorites")
def add_plant_favorite():
    """Add a plant to favorites."""
    payload = request.get_json(force=True) or {}
    user_id = str(payload.get("user_id", "default")).strip()
    plant_id = str(payload.get("plant_id", "")).strip()
    if not user_id or not plant_id:
        return jsonify({"error": "user_id and plant_id are required."}), 400
    conn = None
    try:
        conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
        cursor = conn.cursor()
        fav_id = str(uuid.uuid4())
        cursor.execute("INSERT INTO plant_favorites (id, user_id, plant_id, added_date) VALUES (?, ?, ?, ?)", (fav_id, user_id, plant_id, now_iso()))
        conn.commit()
        payload = {"id": fav_id, "user_id": user_id, "plant_id": plant_id, "added_date": now_iso()}
        return jsonify(payload), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "This plant is already in your favorites."}), 409
    finally:
        if conn is not None:
            conn.close()


@app.delete("/api/plant-favorites/<plant_id>")
def remove_plant_favorite(plant_id: str):
    """Remove a plant from favorites."""
    user_id = request.args.get("user_id", "default")
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM plant_favorites WHERE user_id = ? AND plant_id = ?", (user_id, plant_id))
        conn.commit()
        deleted = cursor.rowcount
        if deleted == 0:
            return jsonify({"error": "Favorite not found."}), 404
        return jsonify({"deleted": plant_id})
    finally:
        conn.close()


# ============= PLANT LIBRARY API =============
@app.post("/api/user-plants")
def create_user_plant():
    """Add a plant to the user's library."""
    payload = request.get_json(force=True) or {}
    user_id = str(payload.get("user_id", "default")).strip()
    plant_id = str(payload.get("plant_id", "")).strip()
    plant_name = str(payload.get("plant_name", "")).strip()
    location_name = str(payload.get("location_name", "")).strip()
    plant_notes = str(payload.get("plant_notes", "")).strip()
    location_zone = str(payload.get("location_zone", "")).strip()
    date_planted = str(payload.get("date_planted", "")).strip() or None
    source_nursery = str(payload.get("source_nursery", "")).strip()
    quantity_planted = int(payload.get("quantity_planted", 1))
    if quantity_planted < 1:
        return jsonify({"error": "quantity_planted must be at least 1."}), 400
    if not user_id or not plant_id:
        return jsonify({"error": "user_id and plant_id are required."}), 400
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
    try:
        cursor = conn.cursor()
        plant_uuid = str(uuid.uuid4())
        cursor.execute(
            "INSERT INTO user_plants (id, user_id, plant_id, plant_name, location_name, location_zone, date_planted, quantity_planted, source_nursery, added_date, plant_notes, health_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plant_uuid, user_id, plant_id, plant_name, location_name, location_zone, date_planted, quantity_planted, source_nursery, now_iso(), plant_notes, "good")
        )
        conn.commit()
        response = {"id": plant_uuid, "user_id": user_id, "plant_id": plant_id, "plant_name": plant_name, "location_name": location_name, "location_zone": location_zone, "date_planted": date_planted, "quantity_planted": quantity_planted, "source_nursery": source_nursery, "added_date": now_iso(), "plant_notes": plant_notes, "health_status": "good"}
        return jsonify(response), 201
    finally:
        conn.close()


@app.get("/api/user-plants")
def get_user_plants():
    """Get all plants in the user's library."""
    user_id = request.args.get("user_id", "default")
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT id, user_id, plant_id, plant_name, location_name, location_zone, date_planted, quantity_planted, source_nursery, added_date, plant_notes, health_status FROM user_plants WHERE user_id = ? ORDER BY added_date DESC", (user_id,))
        plants = [dict(row) for row in cursor.fetchall()]
        return jsonify({"user_id": user_id, "plants": plants})
    finally:
        conn.close()


@app.put("/api/user-plants/<plant_uuid>")
def update_user_plant(plant_uuid: str):
    """Update a plant in the user's library."""
    payload = request.get_json(force=True) or {}
    user_id = payload.get("user_id", "default")
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
    try:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_plants WHERE id = ? AND user_id = ?", (plant_uuid, user_id))
        plant = cursor.fetchone()
        if not plant:
            return jsonify({"error": "Plant not found."}), 404
        
        update_fields = {}
        for key in ["location_name", "location_zone", "date_planted", "quantity_planted", "source_nursery", "plant_notes", "health_status"]:
            if key in payload:
                update_fields[key] = int(payload[key]) if key == "quantity_planted" else str(payload[key]).strip()
        
        if update_fields:
            set_clause = ", ".join(f"{k} = ?" for k in update_fields.keys())
            values = list(update_fields.values()) + [now_iso(), plant_uuid, user_id]
            cursor.execute(f"UPDATE user_plants SET {set_clause}, updated_at = ? WHERE id = ? AND user_id = ?", values)
            conn.commit()
        
        cursor.execute("SELECT id, user_id, plant_id, plant_name, location_name, location_zone, date_planted, quantity_planted, source_nursery, added_date, plant_notes, health_status FROM user_plants WHERE id = ?", (plant_uuid,))
        updated = dict(cursor.fetchone())
        return jsonify(updated)
    finally:
        conn.close()


@app.delete("/api/user-plants/<plant_uuid>")
def delete_user_plant(plant_uuid: str):
    """Remove a plant from the user's library."""
    user_id = request.args.get("user_id", "default")
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH), timeout=30.0)
    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_plants WHERE id = ? AND user_id = ?", (plant_uuid, user_id))
        conn.commit()
        deleted = cursor.rowcount
        if deleted == 0:
            return jsonify({"error": "Plant not found."}), 404
        return jsonify({"deleted": plant_uuid})
    finally:
        conn.close()


@app.get("/api/user-plants/<plant_uuid>/timeline")
def get_plant_timeline(plant_uuid: str):
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH)); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT id, user_plant_id, event_date, event_type, note, photo_url, created_at FROM plant_timeline WHERE user_plant_id = ? ORDER BY event_date DESC", (plant_uuid,)).fetchall(); conn.close()
    return jsonify({"events": [dict(row) for row in rows]})


@app.post("/api/user-plants/<plant_uuid>/timeline")
def add_plant_timeline(plant_uuid: str):
    payload = request.get_json(force=True) or {}
    event_date = str(payload.get("event_date", "")).strip()
    event_type = str(payload.get("event_type", "note")).strip().lower()
    if not event_date or event_type not in {"note", "water", "feed", "prune", "repot", "inspect", "photo"}:
        return jsonify({"error": "event_date and a valid event_type are required."}), 400
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH)); event_id = str(uuid.uuid4())
    conn.execute("INSERT INTO plant_timeline (id, user_plant_id, event_date, event_type, note, photo_url) VALUES (?, ?, ?, ?, ?, ?)", (event_id, plant_uuid, event_date, event_type, str(payload.get("note", "")).strip(), str(payload.get("photo_url", "")).strip()))
    conn.commit(); conn.close()
    return jsonify({"id": event_id, "user_plant_id": plant_uuid, "event_date": event_date, "event_type": event_type}), 201


# ============= PLANT CARE TASKS API =============
@app.post("/api/care-tasks")
def create_care_task():
    """Create a care task for a plant."""
    payload = request.get_json(force=True) or {}
    user_plant_id = str(payload.get("user_plant_id", "")).strip()
    task_type = str(payload.get("task_type", "")).strip()
    frequency_days = int(payload.get("frequency_days", 7))
    if not user_plant_id or not task_type:
        return jsonify({"error": "user_plant_id and task_type are required."}), 400
    if task_type not in {"water", "feed", "prune", "repot", "clean", "inspect"}:
        return jsonify({"error": "Invalid task_type."}), 400
    
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH))
    cursor = conn.cursor()
    task_id = str(uuid.uuid4())
    next_due = (datetime.now(timezone.utc) + timedelta(days=frequency_days)).isoformat()
    cursor.execute(
        "INSERT INTO care_tasks (id, user_plant_id, task_type, frequency_days, next_due_date, status) VALUES (?, ?, ?, ?, ?, ?)",
        (task_id, user_plant_id, task_type, frequency_days, next_due, "pending")
    )
    conn.commit()
    conn.close()
    return jsonify({"id": task_id, "user_plant_id": user_plant_id, "task_type": task_type, "frequency_days": frequency_days, "next_due_date": next_due, "status": "pending"}), 201


@app.get("/api/care-tasks")
def get_care_tasks():
    """Get all care tasks for a user's plants."""
    user_id = request.args.get("user_id", "default")
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ct.id, ct.user_plant_id, ct.task_type, ct.frequency_days, ct.last_done_date, ct.next_due_date, ct.status
        FROM care_tasks ct
        JOIN user_plants up ON ct.user_plant_id = up.id
        WHERE up.user_id = ?
        ORDER BY ct.next_due_date ASC
    """, (user_id,))
    tasks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({"user_id": user_id, "tasks": tasks})


@app.put("/api/care-tasks/<task_id>/complete")
def complete_care_task(task_id: str):
    """Mark a care task as completed."""
    conn = sqlite3.connect(str(PLANT_USER_DB_PATH))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM care_tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        conn.close()
        return jsonify({"error": "Task not found."}), 404
    
    task_dict = dict(task)
    frequency_days = task_dict["frequency_days"]
    next_due = (datetime.now(timezone.utc) + timedelta(days=frequency_days)).isoformat()
    cursor.execute(
        "UPDATE care_tasks SET last_done_date = ?, next_due_date = ?, status = 'completed', updated_at = ? WHERE id = ?",
        (now_iso(), next_due, now_iso(), task_id)
    )
    conn.commit()
    cursor.execute("SELECT id, user_plant_id, task_type, frequency_days, last_done_date, next_due_date, status FROM care_tasks WHERE id = ?", (task_id,))
    updated = dict(cursor.fetchone())
    conn.close()
    return jsonify(updated)

# Register image management API routes
from image_api import register_image_routes
register_image_routes(app)

@app.get("/admin/images")
def image_manager():
    """Serve the image management dashboard."""
    return render_template("image_manager.html")

@app.get("/ai-garden-planner")
def ai_garden_planner():
    """Serve the AI-powered garden planning tool."""
    return render_template("ai_garden_planner.html")

@app.post("/api/generate-garden-plan")
def generate_garden_plan():
    """Generate a garden plan using AI based on user inputs."""
    data = request.get_json() or {}
    prompt = data.get('prompt', '')
    
    if not prompt or len(prompt.strip()) < 10:
        return jsonify({"error": "Please provide a detailed garden description"}), 400
    
    # Load plants database
    with DOG_SAFE_PLANTS_PATH.open(encoding="utf-8") as f:
        plants_data = json.load(f)
    
    plants = plants_data.get("plants", [])
    plants_info = "\n".join([
        f"- {p['name']} ({p['category']}): {p['description']}"
        for p in plants[:100]  # Limit to first 100 for context
    ])
    
    system_prompt = f"""You are a helpful garden planning assistant. You help dog owners create safe, beautiful gardens.
You have access to this database of dog-safe plants:

{plants_info}

When a user describes their garden idea, suggest:
1. Specific plant recommendations with quantities
2. Layout suggestions
3. Care tips for their climate
4. Companion planting ideas

Always prioritize dog safety and practical gardening advice."""
    
    try:
        # For now, return a structured response format
        # In production, this would call an actual LLM API
        return jsonify({
            "status": "success",
            "prompt": prompt,
            "suggestions": [
                "Based on your description, here are personalized recommendations:",
                "1. Plant selection based on your space and climate",
                "2. Suggested layout for optimal growth",
                "3. Dog-safe considerations",
                "4. Maintenance schedule"
            ],
            "note": "AI planning feature - showing template. Connect to OpenAI/Claude API for live suggestions."
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "API endpoint not found."}), 404


@app.errorhandler(405)
def method_not_allowed(error):
    return jsonify({"error": "HTTP method not allowed."}), 405


@app.get("/docs")
def serve_docs():
    """Serve documentation index page."""
    docs_dir = BASE_DIR / "docs"
    if not docs_dir.exists():
        return jsonify({"error": "Documentation not found"}), 404
    
    try:
        readme_path = docs_dir / "README.md"
        if readme_path.exists():
            content = readme_path.read_text(encoding='utf-8')
            # Escape content for JavaScript using JSON
            content_json = json.dumps(content)
            return render_template('docs.html', content_json=content_json)
        return jsonify({"error": "Documentation index not found"}), 404
    except Exception as e:
        app.logger.error(f"Error serving docs: {e}")
        return jsonify({"error": "Could not load documentation"}), 500


@app.get("/docs/<filename>")
def serve_doc_file(filename):
    """Serve individual documentation files as HTML."""
    # Security: only allow .md files and prevent directory traversal
    if not filename.endswith('.md') or '..' in filename:
        return jsonify({"error": "Invalid file"}), 400
    
    docs_dir = BASE_DIR / "docs"
    file_path = docs_dir / filename
    
    if not file_path.exists() or not file_path.is_file():
        return jsonify({"error": "Documentation file not found"}), 404
    
    try:
        content = file_path.read_text(encoding='utf-8')
        content_json = json.dumps(content)
        return render_template('docs.html', content_json=content_json, filename=filename)
    except Exception as e:
        app.logger.error(f"Error serving doc file {filename}: {e}")
        return jsonify({"error": "Could not load documentation file"}), 500

@app.errorhandler(500)
def internal_error(error):
    app.logger.error(f"Internal server error: {error}")
    return jsonify({"error": "Internal server error."}), 500


@app.errorhandler(Exception)
def handle_exception(error):
    app.logger.error(f"Unhandled exception: {error}")
    return jsonify({"error": f"An error occurred: {type(error).__name__}"}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
