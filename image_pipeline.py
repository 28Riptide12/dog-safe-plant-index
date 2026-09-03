"""Plant image resolution pipeline with multi-source waterfall and quality checks.

Waterfall order:
1) Wikimedia Commons
2) GBIF
3) iNaturalist
4) Category placeholder fallback
"""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, ImageStat, UnidentifiedImageError

LOGGER = logging.getLogger("image_pipeline")
if not LOGGER.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    LOGGER.addHandler(_handler)
LOGGER.setLevel(logging.INFO)

REQUEST_TIMEOUT_SECONDS = 3.0
MIN_WIDTH = 400
MIN_HEIGHT = 400
MIN_IMAGE_BYTES = 8 * 1024
MAX_IMAGE_BYTES = 6 * 1024 * 1024
LOW_VARIANCE_STDDEV_THRESHOLD = 2.5
MAX_TRANSPARENT_RATIO = 0.98

PLACEHOLDER_BASE_URL = os.getenv("PLANT_PLACEHOLDER_BASE_URL", "/static/placeholders")
PLACEHOLDERS = {
    "flowers": f"{PLACEHOLDER_BASE_URL}/flowers.svg",
    "fruit": f"{PLACEHOLDER_BASE_URL}/fruit.svg",
    "vegetables": f"{PLACEHOLDER_BASE_URL}/vegetables.svg",
    "herbs": f"{PLACEHOLDER_BASE_URL}/herbs.svg",
    "grasses": f"{PLACEHOLDER_BASE_URL}/grasses.svg",
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "TopsoilPlantGuide/1.0 (image pipeline)"})

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_JSON_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
DEFAULT_BACKUP_DIR = BASE_DIR / "backups"


@dataclass
class ValidationResult:
    ok: bool
    reason: str


def _read_limited_content(response: requests.Response, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            return b""
        chunks.append(chunk)
    return b"".join(chunks)


def validate_image_url(url: str) -> ValidationResult:
    """Validate HTTP health, content type, dimensions, and visual variance.

    Checks:
    1) HTTP response is 200 and content type starts with image/
    2) Image dimensions are > 400x400
    3) Image is not visually blank/solid (very low variance) and not mostly transparent
    """
    if not url:
        return ValidationResult(False, "empty-url")

    try:
        head = SESSION.head(url, allow_redirects=True, timeout=REQUEST_TIMEOUT_SECONDS)
        if head.status_code != 200:
            return ValidationResult(False, f"head-status-{head.status_code}")
        content_type = (head.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type and not content_type.startswith("image/"):
            return ValidationResult(False, f"bad-content-type-{content_type}")
    except requests.RequestException as error:
        LOGGER.debug("HEAD failed for %s: %s", url, error)

    try:
        response = SESSION.get(url, stream=True, timeout=REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
    except requests.RequestException as error:
        return ValidationResult(False, f"http-error-{error.__class__.__name__}")

    with response:
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            return ValidationResult(False, f"bad-content-type-{content_type or 'unknown'}")

        raw = _read_limited_content(response)
        if not raw:
            return ValidationResult(False, "too-large-or-empty")
        if len(raw) < MIN_IMAGE_BYTES:
            return ValidationResult(False, f"too-small-{len(raw)}")

    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("RGBA")
            width, height = image.size
            if width <= MIN_WIDTH or height <= MIN_HEIGHT:
                return ValidationResult(False, f"low-dimensions-{width}x{height}")

            sample = image.resize((128, 128))
            alpha = sample.getchannel("A")
            alpha_values = list(alpha.getdata())
            transparent_ratio = sum(1 for value in alpha_values if value < 8) / max(len(alpha_values), 1)
            if transparent_ratio >= MAX_TRANSPARENT_RATIO:
                return ValidationResult(False, "mostly-transparent")

            rgb = sample.convert("RGB")
            stats = ImageStat.Stat(rgb)
            mean_stddev = sum(stats.stddev) / max(len(stats.stddev), 1)
            if mean_stddev < LOW_VARIANCE_STDDEV_THRESHOLD:
                return ValidationResult(False, f"low-variance-{mean_stddev:.3f}")

    except (UnidentifiedImageError, OSError, ValueError):
        return ValidationResult(False, "corrupt-image")

    return ValidationResult(True, "ok")


def _wikimedia_candidates(scientific_name: str) -> Iterable[str]:
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": scientific_name,
        "gsrnamespace": 6,
        "gsrlimit": 8,
        "prop": "imageinfo",
        "iiprop": "url",
        "iiurlwidth": 1200,
        "format": "json",
    }
    response = SESSION.get(
        "https://commons.wikimedia.org/w/api.php",
        params=params,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {}).values()
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        url = info.get("url") or info.get("thumburl")
        if url:
            yield url


def _gbif_candidates(scientific_name: str) -> Iterable[str]:
    response = SESSION.get(
        "https://api.gbif.org/v1/occurrence/search",
        params={"scientificName": scientific_name, "mediaType": "StillImage", "limit": 12},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    rows = response.json().get("results", [])
    for row in rows:
        for media in row.get("media", []):
            identifier = media.get("identifier")
            if identifier and identifier.startswith("http"):
                yield identifier
                break


def _inaturalist_candidates(scientific_name: str) -> Iterable[str]:
    response = SESSION.get(
        "https://api.inaturalist.org/v1/taxa",
        params={"q": scientific_name, "per_page": 12},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    for row in response.json().get("results", []):
        photo = row.get("default_photo") or {}
        image_url = photo.get("large_url") or photo.get("medium_url") or photo.get("url")
        if image_url:
            yield image_url.replace("square", "large")


def _openverse_candidates(scientific_name: str) -> Iterable[str]:
    response = SESSION.get(
        "https://api.openverse.org/v1/images/",
        params={"q": scientific_name, "page_size": 8, "license_type": "all-cc", "page": 1},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    for row in response.json().get("results", []):
        image_url = str(row.get("url") or row.get("thumbnail") or "").strip()
        if image_url.startswith("http"):
            yield image_url


def _category_placeholder(category: str) -> str:
    return PLACEHOLDERS.get((category or "").strip().casefold(), PLACEHOLDERS["flowers"])


def _pick_first_valid(candidate_urls: Iterable[str], source_name: str) -> str | None:
    for url in candidate_urls:
        result = validate_image_url(url)
        if result.ok:
            LOGGER.info("%s succeeded: %s", source_name, url)
            return url
        LOGGER.info("%s rejected candidate (%s): %s", source_name, result.reason, url)
    return None


def get_best_plant_image(scientific_name: str, category: str) -> str:
    """Return the first healthy image URL from the configured waterfall.

    Logs each stage and gracefully handles timeouts/errors.
    """
    name = (scientific_name or "").strip()
    if not name:
        fallback = _category_placeholder(category)
        LOGGER.info("No scientific name provided. Using category fallback: %s", fallback)
        return fallback

    LOGGER.info("Resolving image for scientific_name=%s category=%s", name, category)

    try:
        LOGGER.info("Trying Wikimedia Commons...")
        found = _pick_first_valid(_wikimedia_candidates(name), "Wikimedia")
        if found:
            return found
    except requests.Timeout:
        LOGGER.warning("Wikimedia failed (timeout) -> Trying GBIF...")
    except requests.RequestException as error:
        LOGGER.warning("Wikimedia failed (%s) -> Trying GBIF...", error.__class__.__name__)

    try:
        LOGGER.info("Trying GBIF...")
        found = _pick_first_valid(_gbif_candidates(name), "GBIF")
        if found:
            return found
    except requests.Timeout:
        LOGGER.warning("GBIF failed (timeout) -> Trying iNaturalist...")
    except requests.RequestException as error:
        LOGGER.warning("GBIF failed (%s) -> Trying iNaturalist...", error.__class__.__name__)

    try:
        LOGGER.info("Trying iNaturalist...")
        found = _pick_first_valid(_inaturalist_candidates(name), "iNaturalist")
        if found:
            return found
    except requests.Timeout:
        LOGGER.warning("iNaturalist failed (timeout) -> Trying Openverse...")
    except requests.RequestException as error:
        LOGGER.warning("iNaturalist failed (%s) -> Trying Openverse...", error.__class__.__name__)

    try:
        LOGGER.info("Trying Openverse...")
        found = _pick_first_valid(_openverse_candidates(name), "Openverse")
        if found:
            return found
    except requests.Timeout:
        LOGGER.warning("Openverse failed (timeout) -> Using category fallback...")
    except requests.RequestException as error:
        LOGGER.warning("Openverse failed (%s) -> Using category fallback...", error.__class__.__name__)

    fallback = _category_placeholder(category)
    LOGGER.info("All sources failed. Using fallback: %s", fallback)
    return fallback


def apply_image_to_json(
    scientific_name: str,
    category: str,
    *,
    json_path: Path = DEFAULT_JSON_PATH,
    plant_id: str | None = None,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    dry_run: bool = False,
) -> tuple[int, str]:
    """Resolve and apply best image URL to matching records in the JSON database."""
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    plants = payload.get("plants", [])

    name_key = (scientific_name or "").strip().casefold()
    id_key = (plant_id or "").strip().casefold()

    matched: list[dict] = []
    for plant in plants:
        plant_scientific = str(plant.get("scientific_name", "")).strip().casefold()
        plant_id_value = str(plant.get("id", "")).strip().casefold()
        if id_key and plant_id_value == id_key:
            matched.append(plant)
            continue
        if not id_key and plant_scientific == name_key:
            matched.append(plant)

    if not matched:
        raise ValueError("No matching plants found in JSON for the given selector.")

    best_url = get_best_plant_image(scientific_name, category)
    updated = 0
    for plant in matched:
        previous = str(plant.get("image_url", "")).strip()
        if previous != best_url:
            plant["image_url"] = best_url
            if best_url.startswith("http"):
                plant["image_source_url"] = best_url
            updated += 1

    if dry_run:
        LOGGER.info("Dry run: would update %s records in %s", updated, json_path)
        return updated, best_url

    if updated > 0:
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_name = f"dog-safe-plants-pipeline-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        shutil.copy2(json_path, backup_dir / backup_name)
        json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        LOGGER.info("Updated %s records in %s (backup: %s)", updated, json_path, backup_name)
    else:
        LOGGER.info("No changes needed in %s", json_path)

    return updated, best_url


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Resolve best plant image URL.")
    parser.add_argument("scientific_name")
    parser.add_argument("--category", default="flowers")
    parser.add_argument("--apply-json", default=None, help="Apply resolved URL to matching records in the given JSON file")
    parser.add_argument("--plant-id", default=None, help="Optional precise plant id selector for JSON updates")
    parser.add_argument("--dry-run", action="store_true", help="Preview JSON updates without writing")
    args = parser.parse_args()

    if args.apply_json:
        target_path = Path(args.apply_json)
        changed, url = apply_image_to_json(
            args.scientific_name,
            args.category,
            json_path=target_path,
            plant_id=args.plant_id,
            dry_run=args.dry_run,
        )
        print(url)
        print(f"records_updated={changed}")
    else:
        print(get_best_plant_image(args.scientific_name, args.category))
