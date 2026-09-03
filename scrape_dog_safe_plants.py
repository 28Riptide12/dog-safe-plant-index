"""Collect dog non-toxic plant entries from the ASPCA plant index.

Includes robust image selection:
- content-type and status validation
- retry with exponential backoff for transient/rate-limited failures
- blank/white/transparent/corrupt image rejection
- multi-source fallback waterfall (ASPCA -> Wikimedia -> iNaturalist -> GBIF)
- category placeholder fallback when no valid photo can be found
"""

from __future__ import annotations

import argparse
import io
import json
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

BASE_DIR = Path(__file__).resolve().parent
INDEX_URL = "https://www.aspca.org/pet-care/animal-poison-control/dogs-plant-list"
DEFAULT_OUTPUT = BASE_DIR / "database" / "dog_safe_plants_scraped.json"
HEADERS = {"User-Agent": "TopsoilPlantGuide/1.0 (research catalogue)"}
CATEGORIES = {"flowers", "fruit", "vegetables", "herbs", "grasses"}
MIN_IMAGE_BYTES = 8 * 1024
MIN_SIDE = 120
WHITE_PIXEL_THRESHOLD = 0.985
ALPHA_PIXEL_THRESHOLD = 0.985
MAX_IMAGE_BYTES = 6 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 14
PLACEHOLDER_BY_CATEGORY = {
    "flowers": "/static/placeholders/flowers.svg",
    "fruit": "/static/placeholders/fruit.svg",
    "vegetables": "/static/placeholders/vegetables.svg",
    "herbs": "/static/placeholders/herbs.svg",
    "grasses": "/static/placeholders/grasses.svg",
}
BAD_IMAGE_PATTERNS = re.compile(r"(?:noimage|imageunavailable|/image(?:_0)?\.jpg)", re.I)


def clean(value: str) -> str:
    return " ".join(value.split())


def category_for(name: str, scientific_name: str, text: str) -> str:
    combined = f"{name} {scientific_name} {text}".casefold()
    if any(word in combined for word in ("grass", "bamboo", "sedge", "reed", "rush")):
        return "grasses"
    if any(word in combined for word in ("basil", "rosemary", "sage", "thyme", "mint", "parsley", "herb", "oregano", "dill", "coriander")):
        return "herbs"
    if any(word in combined for word in ("strawberry", "blueberry", "raspberry", "blackberry", "apple", "pear", "fig", "grape", "berry", "fruit")):
        return "fruit"
    if any(word in combined for word in ("carrot", "bean", "pea", "lettuce", "spinach", "cucumber", "squash", "pumpkin", "vegetable", "broccoli", "kale")):
        return "vegetables"
    return "flowers"


def request_with_retry(session: requests.Session, url: str, *, params: dict | None = None, stream: bool = False, retries: int = 2, base_backoff: float = 0.5) -> requests.Response:
    """HTTP request with exponential backoff for 429/5xx and connection issues."""
    delay = base_backoff
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = session.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT_SECONDS, stream=stream)
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
        except requests.RequestException as error:
            last_error = error
            if attempt >= retries:
                raise
            time.sleep(delay)
            delay *= 2
    if last_error:
        raise last_error
    raise RuntimeError("Request retry failed without explicit error.")


def validate_image_binary(blob: bytes) -> tuple[bool, str]:
    """Reject tiny, blank, transparent, or corrupt images."""
    if len(blob) < MIN_IMAGE_BYTES:
        return False, f"too-small:{len(blob)}"
    if len(blob) > MAX_IMAGE_BYTES:
        return False, f"too-large:{len(blob)}"
    try:
        with Image.open(io.BytesIO(blob)) as image:
            image = image.convert("RGBA")
            width, height = image.size
            if width < MIN_SIDE or height < MIN_SIDE:
                return False, f"low-resolution:{width}x{height}"
            # Downsample for quick pixel-quality checks.
            sample = image.resize((96, 96))
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


def download_if_valid_image(session: requests.Session, url: str, *, retries: int = 2) -> tuple[bool, str]:
    """Validate HTTP headers and image pixels without persisting files."""
    response = request_with_retry(session, url, stream=True, retries=retries)
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if not content_type.startswith("image/"):
            return False, f"bad-content-type:{content_type or 'unknown'}"
        body = read_response_limited(response, MAX_IMAGE_BYTES + 1)
        if not body:
            return False, "too-large-or-empty"
        ok, reason = validate_image_binary(body)
        return ok, reason
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
    response = request_with_retry(session, "https://api.inaturalist.org/v1/taxa", params={"q": query, "per_page": min(max(limit, 1), 12)}, retries=retries)
    response.raise_for_status()
    out = []
    for result in response.json().get("results", []):
        photo = result.get("default_photo") or {}
        image_url = photo.get("medium_url") or photo.get("url") or photo.get("square_url")
        taxon_id = result.get("id")
        if image_url and taxon_id:
            image_url = image_url.replace("square", "large")
            out.append({"provider": "inaturalist", "image_url": image_url, "image_source_url": f"https://www.inaturalist.org/taxa/{taxon_id}"})
    return out[:limit]


def gbif_candidates(session: requests.Session, scientific_name: str, *, retries: int = 2, limit: int = 6, timeout_seconds: float = REQUEST_TIMEOUT_SECONDS) -> list[dict[str, str]]:
    if not scientific_name:
        return []
    match = request_with_retry(session, "https://api.gbif.org/v1/species/match", params={"name": scientific_name}, retries=retries)
    match.raise_for_status()
    usage_key = match.json().get("usageKey")
    if not usage_key:
        return []
    occ = request_with_retry(
        session,
        "https://api.gbif.org/v1/occurrence/search",
        params={"taxonKey": usage_key, "mediaType": "StillImage", "limit": min(max(limit * 2, 2), 20)},
        retries=retries,
    )
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


def category_placeholder(category: str) -> dict[str, str]:
    image_url = PLACEHOLDER_BY_CATEGORY.get(category, PLACEHOLDER_BY_CATEGORY["flowers"])
    return {
        "provider": "placeholder",
        "image_url": image_url,
        "image_source_url": image_url,
    }


def select_best_image(
    session: requests.Session,
    *,
    category: str,
    scientific_name: str,
    common_name: str,
    aspca_candidates: list[str],
    include_gbif: bool,
    retries: int,
    max_candidates_per_provider: int,
    timeout_seconds: float,
    plant_budget_seconds: float,
) -> dict[str, str]:
    """Return first clean image from waterfall sources, else category placeholder."""
    candidates: list[dict[str, str]] = []
    started = time.monotonic()
    for url in aspca_candidates:
        if not url or BAD_IMAGE_PATTERNS.search(url):
            continue
        candidates.append({"provider": "aspca", "image_url": url, "image_source_url": ""})
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
        image_url = candidate["image_url"]
        if image_url in seen:
            continue
        seen.add(image_url)
        try:
            ok, _reason = download_if_valid_image(session, image_url, retries=retries)
            if ok:
                return candidate
        except requests.RequestException:
            continue
    return category_placeholder(category)


def entry_from_page(session: requests.Session, url: str, *, include_gbif: bool, retries: int, max_candidates_per_provider: int, timeout_seconds: float, plant_budget_seconds: float) -> dict[str, str] | None:
    response = request_with_retry(session, url, retries=retries)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    main = soup.select_one(".l-main") or soup
    text = clean(main.get_text(" ", strip=True))
    if not re.search(r"Non-Toxicity:\s*Non-Toxic to Dogs", text, re.I):
        return None
    title = soup.select_one("h1")
    name = clean(title.get_text(" ", strip=True) if title else url.rstrip("/").rsplit("/", 1)[-1].replace("-", " "))
    name = re.sub(r"^Toxic and Non-toxic Plants:\s*", "", name, flags=re.I)
    scientific = re.search(r"Scientific Name:\s*([^|]+?)(?:\s+Family:|\s+Toxicity:|\s+Non-Toxicity:)", text, re.I)
    scientific_name = clean(scientific.group(1)) if scientific else name
    aspca_images = []
    exact = next((img.get("src") for img in main.find_all("img") if img.get("src") and img.get("alt", "").casefold() == name.casefold()), None)
    if exact:
        aspca_images.append(urljoin(url, exact))
    for img in main.find_all("img"):
        src = img.get("src")
        if not src:
            continue
        if "lead-gen" in src or "sidebar" in src or "logo" in src:
            continue
        if not urlparse(src).path.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        aspca_images.append(urljoin(url, src))

    plant_id = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    category = category_for(name, scientific_name, text)
    selected = select_best_image(
        session,
        category=category,
        scientific_name=scientific_name,
        common_name=name,
        aspca_candidates=aspca_images,
        include_gbif=include_gbif,
        retries=retries,
        max_candidates_per_provider=max_candidates_per_provider,
        timeout_seconds=timeout_seconds,
        plant_budget_seconds=plant_budget_seconds,
    )
    return {
        "id": plant_id,
        "name": name,
        "scientific_name": scientific_name,
        "category": category,
        "safety_status": "Non-toxic to dogs",
        "image_url": selected["image_url"],
        "image_source_url": selected.get("image_source_url", url),
        "description": f"ASPCA-listed dog non-toxic plant: {name}.",
        "source_url": url,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--delay", type=float, default=0.25)
    parser.add_argument("--quick", action="store_true", help="Faster run: fewer retries/candidates and skip GBIF")
    parser.add_argument("--max-pages", type=int, default=None, help="Scrape only first N plant pages")
    parser.add_argument("--progress-every", type=int, default=10, help="Print progress every N pages")
    parser.add_argument("--no-gbif", action="store_true", help="Skip GBIF fallback provider")
    args = parser.parse_args()
    session = requests.Session()
    retries = 0 if args.quick else 1
    timeout_seconds = 6.0 if args.quick else REQUEST_TIMEOUT_SECONDS
    plant_budget_seconds = 14.0 if args.quick else 45.0
    max_candidates_per_provider = 1 if args.quick else 4
    include_gbif = (not args.no_gbif) and (not args.quick)

    index = request_with_retry(session, INDEX_URL, retries=retries)
    index.raise_for_status()
    soup = BeautifulSoup(index.text, "html.parser")
    urls = sorted({urljoin(INDEX_URL, link["href"]) for link in soup.select('a[href*="/toxic-and-non-toxic-plants/"]')})
    if args.max_pages is not None:
        urls = urls[: max(0, args.max_pages)]
    plants = []
    print(f"scraping {len(urls)} pages (quick={args.quick}, gbif={include_gbif}, retries={retries})", flush=True)
    for number, url in enumerate(urls, start=1):
        try:
            plant = entry_from_page(
                session,
                url,
                include_gbif=include_gbif,
                retries=retries,
                max_candidates_per_provider=max_candidates_per_provider,
                timeout_seconds=timeout_seconds,
                plant_budget_seconds=plant_budget_seconds,
            )
            if plant and plant["category"] in CATEGORIES:
                plants.append(plant)
        except requests.RequestException as error:
            print(f"skipped {url}: {error}")
        if number < len(urls):
            time.sleep(args.delay)
        if number % max(1, args.progress_every) == 0 or number == len(urls):
            print(f"checked {number}/{len(urls)}; safe entries={len(plants)}")
    plants.sort(key=lambda item: item["name"].casefold())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"source": INDEX_URL, "scraped_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "plants": plants}, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(plants)} dog non-toxic plants to {args.output}")


if __name__ == "__main__":
    main()
