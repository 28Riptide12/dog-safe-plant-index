"""Audit and repair plant image URLs in database/dog_safe_plants.json.

This script validates current image URLs, rejects broken/blank/placeholder images,
then applies a fallback waterfall:
1) existing URL (if valid)
2) Wikimedia Commons by scientific/common name
3) iNaturalist taxa photo
4) GBIF occurrence media
5) category-based local placeholder

Usage:
  py tools/audit_plant_images.py --in-place
  py tools/audit_plant_images.py --write-report
"""

from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
BACKUP_DIR = BASE_DIR / "backups"
GENERATED_DIR = BASE_DIR / "data" / "generated-json"
REPORT_PATH = GENERATED_DIR / "image_audit_report.json"

HEADERS = {"User-Agent": "TopsoilPlantGuide/1.0 (image audit)"}
MIN_IMAGE_BYTES = 8 * 1024
MAX_IMAGE_BYTES = 6 * 1024 * 1024
MIN_SIDE = 350
MAX_TOTAL_PIXELS = 40_000_000
WHITE_PIXEL_THRESHOLD = 0.985
ALPHA_PIXEL_THRESHOLD = 0.985
REQUEST_TIMEOUT_SECONDS = 14
BAD_IMAGE_PATTERNS = re.compile(r"(?:noimage|imageunavailable|/image(?:_0)?\.jpg)", re.I)

PLACEHOLDER_BY_CATEGORY = {
    "flowers": "/static/placeholders/flowers.svg",
    "fruit": "/static/placeholders/fruit.svg",
    "vegetables": "/static/placeholders/vegetables.svg",
    "herbs": "/static/placeholders/herbs.svg",
    "grasses": "/static/placeholders/grasses.svg",
}


def request_with_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    stream: bool = False,
    retries: int = 2,
    base_backoff: float = 0.5,
    timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
) -> requests.Response:
    delay = base_backoff
    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, headers=HEADERS, timeout=timeout_seconds, stream=stream)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                if attempt >= retries:
                    response.raise_for_status()
                retry_after = response.headers.get("Retry-After")
                wait = float(retry_after) if retry_after and retry_after.isdigit() else delay
                response.close()
                time.sleep(wait)
                delay *= 2
                continue
            return response
        except requests.RequestException:
            if attempt >= retries:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("request_with_retry exhausted unexpectedly")


def validate_image_binary(blob: bytes) -> tuple[bool, str]:
    if len(blob) < MIN_IMAGE_BYTES:
        return False, f"too-small:{len(blob)}"
    if len(blob) > MAX_IMAGE_BYTES:
        return False, f"too-large:{len(blob)}"
    try:
        with Image.open(io.BytesIO(blob)) as image:
            width, height = image.size
            if width < MIN_SIDE or height < MIN_SIDE:
                return False, f"low-resolution:{width}x{height}"
            if width * height > MAX_TOTAL_PIXELS:
                return False, f"too-many-pixels:{width}x{height}"

            sample = image.copy()
            sample.thumbnail((96, 96))
            sample = sample.convert("RGBA")

            pixels = list(sample.getdata())
            total = len(pixels)
            transparent = sum(1 for r, g, b, a in pixels if a < 8)
            almost_white = sum(1 for r, g, b, a in pixels if a >= 8 and r > 245 and g > 245 and b > 245)
            if transparent / total >= ALPHA_PIXEL_THRESHOLD:
                return False, "mostly-transparent"
            if almost_white / total >= WHITE_PIXEL_THRESHOLD:
                return False, "mostly-white"
            return True, "ok"
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "corrupt"


def read_response_limited(response: requests.Response, max_bytes: int) -> bytes:
    """Read response in chunks and stop if payload exceeds max_bytes."""
    parts: list[bytes] = []
    total = 0
    for chunk in response.iter_content(chunk_size=65536):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            return b""
        parts.append(chunk)
    return b"".join(parts)


def check_image_url(session: requests.Session, url: str, *, retries: int = 2, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> tuple[bool, str]:
    if not url or url.startswith("/static/placeholders/"):
        return False, "placeholder"
    if BAD_IMAGE_PATTERNS.search(url):
        return False, "known-placeholder-pattern"
    response = request_with_retry(session, url, stream=True, retries=retries, timeout_seconds=timeout_seconds)
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            return False, f"bad-content-type:{content_type or 'unknown'}"
        body = read_response_limited(response, MAX_IMAGE_BYTES + 1)
        if not body:
            return False, "too-large-or-empty"
        return validate_image_binary(body)
    finally:
        response.close()


def wikimedia_candidates(session: requests.Session, scientific_name: str, common_name: str, *, retries: int = 2, limit: int = 6, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> list[dict[str, str]]:
    query = scientific_name or common_name
    if not query:
        return []
    response = request_with_retry(
        session,
        "https://commons.wikimedia.org/w/api.php",
        params={
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrnamespace": 6,
            "gsrlimit": min(max(limit, 1), 12),
            "prop": "imageinfo",
            "iiprop": "url",
            "iiurlwidth": 900,
            "format": "json",
        },
        retries=retries,
        timeout_seconds=timeout_seconds,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {}).values()
    out = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        image_url = info.get("thumburl") or info.get("url")
        source_url = info.get("descriptionurl") or ""
        if image_url:
            out.append({"provider": "wikimedia", "image_url": image_url, "image_source_url": source_url})
    return out[:limit]


def inaturalist_candidates(session: requests.Session, scientific_name: str, common_name: str, *, retries: int = 2, limit: int = 6, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> list[dict[str, str]]:
    query = scientific_name or common_name
    if not query:
        return []
    response = request_with_retry(session, "https://api.inaturalist.org/v1/taxa", params={"q": query, "per_page": min(max(limit, 1), 12)}, retries=retries, timeout_seconds=timeout_seconds)
    response.raise_for_status()
    out = []
    for result in response.json().get("results", []):
        photo = result.get("default_photo") or {}
        image_url = photo.get("large_url") or photo.get("medium_url") or photo.get("url") or photo.get("square_url")
        taxon_id = result.get("id")
        if image_url and taxon_id:
            candidates = [
                image_url.replace("/square.", "/original."),
                image_url.replace("/medium.", "/original."),
                image_url.replace("/large.", "/original."),
                image_url.replace("square", "large"),
                image_url,
            ]
            for candidate_url in dict.fromkeys(candidates):
                out.append({"provider": "inaturalist", "image_url": candidate_url, "image_source_url": f"https://www.inaturalist.org/taxa/{taxon_id}"})
    return out[:limit]


def gbif_candidates(session: requests.Session, scientific_name: str, *, retries: int = 2, limit: int = 6, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> list[dict[str, str]]:
    if not scientific_name:
        return []
    match = request_with_retry(session, "https://api.gbif.org/v1/species/match", params={"name": scientific_name}, retries=retries, timeout_seconds=timeout_seconds)
    match.raise_for_status()
    usage_key = match.json().get("usageKey")
    if not usage_key:
        return []
    occ = request_with_retry(session, "https://api.gbif.org/v1/occurrence/search", params={"taxonKey": usage_key, "mediaType": "StillImage", "limit": min(max(limit * 2, 2), 20)}, retries=retries, timeout_seconds=timeout_seconds)
    occ.raise_for_status()
    out = []
    for row in occ.json().get("results", []):
        for media in row.get("media", []):
            image_url = media.get("identifier")
            source_url = media.get("references") or f"https://www.gbif.org/occurrence/{row.get('key')}"
            if image_url and image_url.startswith("http"):
                out.append({"provider": "gbif", "image_url": image_url, "image_source_url": source_url})
                break
    return out[:limit]


def placeholder_for(category: str) -> dict[str, str]:
    image_url = PLACEHOLDER_BY_CATEGORY.get(category, PLACEHOLDER_BY_CATEGORY["flowers"])
    return {"provider": "placeholder", "image_url": image_url, "image_source_url": image_url}


def choose_replacement(
    session: requests.Session,
    plant: dict,
    *,
    include_gbif: bool,
    retries: int,
    max_candidates_per_provider: int,
    timeout_seconds: float,
    plant_budget_seconds: float,
) -> dict[str, str]:
    scientific_name = str(plant.get("scientific_name", "")).strip()
    common_name = str(plant.get("name", "")).strip()
    category = str(plant.get("category", "flowers")).strip().casefold() or "flowers"

    candidates: list[dict[str, str]] = []
    started = time.monotonic()
    try:
        candidates.extend(wikimedia_candidates(session, scientific_name, common_name, retries=retries, limit=max_candidates_per_provider, timeout_seconds=timeout_seconds))
    except requests.RequestException:
        pass
    try:
        candidates.extend(inaturalist_candidates(session, scientific_name, common_name, retries=retries, limit=max_candidates_per_provider, timeout_seconds=timeout_seconds))
    except requests.RequestException:
        pass
    if include_gbif:
        try:
            candidates.extend(gbif_candidates(session, scientific_name, retries=retries, limit=max_candidates_per_provider, timeout_seconds=timeout_seconds))
        except requests.RequestException:
            pass

    seen = set()
    for candidate in candidates:
        if time.monotonic() - started > plant_budget_seconds:
            break
        image_url = candidate.get("image_url", "")
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        try:
            ok, _reason = check_image_url(session, image_url, retries=retries, timeout_seconds=timeout_seconds)
            if ok:
                return candidate
        except requests.RequestException:
            continue
    return placeholder_for(category)


def run_audit(
    in_place: bool,
    write_report: bool,
    *,
    quick: bool,
    max_plants: int | None,
    progress_every: int,
    include_gbif: bool,
) -> tuple[int, int, list[dict]]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    plants = payload.get("plants", [])
    if max_plants is not None:
        plants = plants[: max(0, max_plants)]
    changed = 0
    flagged = 0
    report_rows: list[dict] = []

    session = requests.Session()
    total = len(plants)
    retries = 0 if quick else 1
    timeout_seconds = 6.0 if quick else 12.0
    plant_budget_seconds = 14.0 if quick else 45.0
    max_candidates_per_provider = 1 if quick else 4
    allow_gbif = include_gbif and not quick

    print(f"auditing {total} plants (quick={quick}, gbif={allow_gbif}, retries={retries})", flush=True)

    for index, plant in enumerate(plants, start=1):
        current = str(plant.get("image_url", "")).strip()
        ok = False
        reason = "missing"
        if current:
            try:
                ok, reason = check_image_url(session, current, retries=retries, timeout_seconds=timeout_seconds)
            except requests.RequestException:
                ok, reason = False, "request-failed"

        if ok:
            if progress_every and (index % progress_every == 0 or index == total):
                print(f"progress {index}/{total}: flagged={flagged}, changed={changed}", flush=True)
            continue

        flagged += 1
        replacement = choose_replacement(
            session,
            plant,
            include_gbif=allow_gbif,
            retries=retries,
            max_candidates_per_provider=max_candidates_per_provider,
            timeout_seconds=timeout_seconds,
            plant_budget_seconds=plant_budget_seconds,
        )
        previous = current
        plant["image_url"] = replacement["image_url"]
        if replacement.get("image_source_url"):
            plant["image_source_url"] = replacement["image_source_url"]
        changed += 1
        report_rows.append(
            {
                "id": plant.get("id"),
                "name": plant.get("name"),
                "previous_image_url": previous,
                "replacement_image_url": replacement["image_url"],
                "replacement_provider": replacement["provider"],
                "reason": reason,
            }
        )
        if progress_every and (index % progress_every == 0 or index == total):
            print(f"progress {index}/{total}: flagged={flagged}, changed={changed}", flush=True)

    if in_place and changed:
        BACKUP_DIR.mkdir(exist_ok=True)
        backup_name = f"dog-safe-plants-audit-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        shutil.copy2(DATA_PATH, BACKUP_DIR / backup_name)
        DATA_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    if write_report:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(
            json.dumps(
                {
                    "audited_at": datetime.now(timezone.utc).isoformat(),
                    "total_plants": len(plants),
                    "flagged": flagged,
                    "changed": changed,
                    "rows": report_rows,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    return flagged, changed, report_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in-place", action="store_true", help="Write repaired URLs back to database/dog_safe_plants.json")
    parser.add_argument("--write-report", action="store_true", help="Write a JSON report of all flagged/replaced rows")
    parser.add_argument("--quick", action="store_true", help="Faster run: fewer retries/candidates and skips GBIF")
    parser.add_argument("--max-plants", type=int, default=None, help="Audit only the first N plants")
    parser.add_argument("--progress-every", type=int, default=20, help="Print progress every N plants")
    parser.add_argument("--no-gbif", action="store_true", help="Skip GBIF fallback provider")
    args = parser.parse_args()

    flagged, changed, _ = run_audit(
        in_place=args.in_place,
        write_report=args.write_report,
        quick=args.quick,
        max_plants=args.max_plants,
        progress_every=max(1, args.progress_every),
        include_gbif=not args.no_gbif,
    )
    print(f"audited {DATA_PATH.name}: flagged={flagged}, changed={changed}")


if __name__ == "__main__":
    main()
