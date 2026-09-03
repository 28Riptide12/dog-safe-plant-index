"""Harvest horticultural detail (sun/soil/hardiness/lifecycle) from RHS plant pages.

RHS's plant search/detail pages are a JS-rendered SPA, so this uses Playwright
(headless Chromium) to render pages before extracting text. This is
non-safety enrichment only: it never touches safety_status, never adds new
plants, and never writes to dog_safe_plants.json or the review queue. It only
fills *missing* fields in database/plant_lifecycle_and_hardiness.json for
plants that already exist in the catalogue, with source URLs recorded in
_meta.source_urls for traceability. Existing non-empty values are never
overwritten.

Runs several plants concurrently (async Playwright, default 6 workers) instead
of one at a time, which is several times faster than the original serial
version. Plants that already have an RHS source recorded are skipped by
default, so you can safely run this in short batches (--batch-size) and each
run will pick up where the last one left off.

Interactive controls while running (Windows console):
  P  - pause / resume (workers finish their current plant, then idle)
  Q  - quit gracefully (workers stop picking up new plants; progress is saved)
  Ctrl+C also stops gracefully and saves progress made up to that point.

Progress display includes elapsed time, plants/sec, and an ETA. Results are
autosaved to disk every --save-every plants (default 10).

Run with no arguments at all to get an interactive menu (batch size, worker
count, delay). Otherwise use flags directly, e.g. for scripting/automation:

Usage:
  python harvest_plant_horticulture.py                  # interactive menu
  python harvest_plant_horticulture.py --batch-size 50   # next 50 not-yet-done plants
  python harvest_plant_horticulture.py --workers 10       # more concurrency = faster
  python harvest_plant_horticulture.py --plant-id lavender
  python harvest_plant_horticulture.py --dry-run
  python harvest_plant_horticulture.py --redo-all         # ignore skip-done, refetch everything

Requires: pip install playwright && playwright install chromium
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import BrowserContext, async_playwright
import requests

try:
    import msvcrt  # Windows-only, used for non-blocking keypress detection.
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None


BASE_DIR = Path(__file__).resolve().parent
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
LIFECYCLE_HARDINESS_PATH = BASE_DIR / "database" / "plant_lifecycle_and_hardiness.json"
REVIEW_QUEUE_PATH = BASE_DIR / "database" / "plant_review_queue.json"
RHS_SEARCH_URL = "https://www.rhs.org.uk/plants/search-results"
PPH_SEARCH_URL = "https://www.petpoisonhelpline.com/poison"
WIKIPEDIA_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/summary"
PAGE_TIMEOUT_MS = 20000


async def find_rhs_detail_url(context: BrowserContext, scientific_name: str, common_name: str = "") -> Optional[str]:
    """Search RHS by scientific name and return the closest plant detail page URL.

    Falls back through progressively looser queries because many catalogue scientific
    names are genus-only placeholders (e.g. "Alocasia spp.") or contain typos inherited
    from the ASPCA source data (e.g. "Neoregalia" for "Aregelia"), which an exact-name
    search on RHS won't match. Falling back to a cleaned genus-only query, then the
    common name, recovers a large share of these without guessing at safety data.
    """
    def clean_query(raw: str) -> str:
        # Strip cultivar/variety/species-placeholder suffixes RHS won't recognize literally.
        cleaned = re.sub(r"\bspp\.?\b", "", raw, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bcv\.?\s*.*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bvar\.?\s*.*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"['\".]", "", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    queries = []
    cleaned_scientific = clean_query(scientific_name)
    if cleaned_scientific:
        queries.append(cleaned_scientific)
    genus_only = cleaned_scientific.split(" ")[0] if cleaned_scientific else ""
    if genus_only and genus_only.casefold() not in {q.casefold() for q in queries}:
        queries.append(genus_only)
    if common_name and common_name.casefold() not in {q.casefold() for q in queries}:
        queries.append(common_name)

    page = await context.new_page()
    try:
        for query in queries:
            try:
                await page.goto(f"{RHS_SEARCH_URL}?query={query}", wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
                await page.wait_for_timeout(500)
                links = await page.eval_on_selector_all("a", "els => els.map(e => e.href)")
            except Exception:
                continue

            detail_links = [link for link in links if "/details" in link and "/plants/" in link]
            if not detail_links:
                continue

            # Prefer the plain species page (no cultivar in parentheses/quotes) if present,
            # since that best matches a catalogue entry recorded only by scientific name.
            species_slug = re.sub(r"[^a-z]+", "-", query.casefold()).strip("-")
            for link in detail_links:
                slug = link.rsplit("/", 2)[-2] if link.endswith("/details") else ""
                if slug == species_slug:
                    return link
            return detail_links[0]
        return None
    finally:
        await page.close()


async def parse_rhs_detail(context: BrowserContext, url: str) -> dict[str, str]:
    """Extract horticultural facts from a rendered RHS plant detail page."""
    facts: dict[str, str] = {}
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(500)
        text = await page.inner_text("body")
    except Exception:
        return facts
    finally:
        await page.close()

    def grab(label: str) -> str:
        match = re.search(rf"{re.escape(label)}\s*\n\s*([^\n]{{1,160}})", text)
        return match.group(1).strip() if match else ""

    sun = grab("Position")
    soil = grab("Growing Conditions") or grab("Soil Types")
    hardiness = grab("Hardiness")
    max_height = grab("Max Height")
    max_spread = grab("Max Spread")
    habit = grab("Habit")
    foliage = grab("Foliage")

    if sun:
        facts["sun_exposure"] = sun
    if soil:
        facts["soil_type"] = soil
    if hardiness:
        zone_match = re.search(r"\bH\d[a-z]?\b", hardiness)
        facts["hardiness_zone"] = zone_match.group(0) if zone_match else hardiness
    if max_height or max_spread:
        parts = []
        if max_height:
            parts.append(f"Height: {max_height}")
        if max_spread:
            parts.append(f"Spread: {max_spread}")
        facts["mature_size"] = ", ".join(parts)
    if habit:
        facts["growth_habit"] = habit
    if foliage:
        facts["foliage_type"] = foliage
    return facts


async def fetch_wikipedia_summary(scientific_name: str, common_name: str) -> dict[str, str]:
    """Fetch a plain-text description/native-region hint from Wikipedia's REST summary API.

    No Playwright needed -- Wikipedia's summary endpoint is a simple static JSON API,
    so this runs a plain HTTP request in a worker thread instead of a browser page.
    """
    facts: dict[str, str] = {}
    for title in (scientific_name, common_name):
        if not title:
            continue
        try:
            response = await asyncio.to_thread(
                requests.get,
                f"{WIKIPEDIA_SUMMARY_URL}/{requests.utils.quote(title)}",
                timeout=10,
                headers={"User-Agent": "dog-safe-plant-app/1.0 (educational hobby project)"},
            )
        except Exception:
            continue
        if response.status_code != 200:
            continue
        try:
            data = response.json()
        except ValueError:
            continue
        if data.get("type") == "disambiguation":
            continue
        extract = str(data.get("extract", "")).strip()
        if extract and len(extract) > 40:
            facts["wikipedia_summary"] = extract[:500]
            facts["wikipedia_url"] = data.get("content_urls", {}).get("desktop", {}).get("page", "")
            return facts
    return facts


async def find_pph_detail_url(context: BrowserContext, name: str, scientific_name: str) -> Optional[str]:
    """Guess the Pet Poison Helpline detail-page slug from the plant's common/scientific name.

    PPH pages use simple slugs (e.g. /poison/lily-of-the-valley/, /poison/alocasia/) rather
    than a working full-text search, so this tries the most likely slugs directly and
    falls back to the site's own poison index if none resolve.
    """
    candidates = []
    for candidate_name in (name, scientific_name):
        if not candidate_name:
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", candidate_name.casefold()).strip("-")
        if slug:
            candidates.append(slug)

    page = await context.new_page()
    try:
        for slug in candidates:
            url = f"{PPH_SEARCH_URL}/{slug}/"
            try:
                response = await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
            except Exception:
                continue
            if response is not None and response.status == 200:
                await page.wait_for_timeout(300)
                text = await page.inner_text("body")
                if "Toxicity to pets" in text or "SCIENTIFIC NAME" in text:
                    return url
        return None
    finally:
        await page.close()


async def parse_pph_detail(context: BrowserContext, url: str) -> dict[str, str]:
    """Extract a plain toxicity-summary snippet from a Pet Poison Helpline page.

    This is review-queue-only data: it is never written as a safety verdict directly,
    only stored as a source note for a human to review alongside our own ASPCA-based
    safety_status.
    """
    facts: dict[str, str] = {}
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=PAGE_TIMEOUT_MS)
        await page.wait_for_timeout(400)
        text = await page.inner_text("body")
    except Exception:
        return facts
    finally:
        await page.close()

    match = re.search(r"Toxicity to pets\s*\n(.+?)(?:Speak to an expert|DISCLAIMER)", text, re.DOTALL)
    if match:
        note = re.sub(r"\n+", " ", match.group(1)).strip()
        note = re.sub(r"\s{2,}", " ", note)
        if note:
            facts["pph_toxicity_note"] = note[:600]
            facts["pph_source_url"] = url
    return facts


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, content: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


class KeyboardController:
    """Watches for P (pause/resume) and Q (quit) keypresses without blocking the main loop."""

    def __init__(self) -> None:
        self.paused = False
        self.quit_requested = False
        self._stop = False
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if msvcrt is None:
            print("(Interactive pause/quit controls need Windows console support; not available here.)")
            return
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()
        print("Controls: press P to pause/resume, Q to quit gracefully, Ctrl+C also works.")

    def stop(self) -> None:
        self._stop = True

    def _watch(self) -> None:
        while not self._stop:
            if msvcrt.kbhit():
                key = msvcrt.getwch().lower()
                if key == "p":
                    self.paused = not self.paused
                    print("\n[PAUSED - press P to resume]" if self.paused else "\n[RESUMED]")
                elif key == "q":
                    self.quit_requested = True
                    print("\n[QUIT requested - finishing in-flight plants, then stopping]")
            time.sleep(0.1)

    async def wait_while_paused(self) -> None:
        while self.paused and not self.quit_requested:
            await asyncio.sleep(0.2)


def has_source_marker(entry: dict, marker_field: Optional[str] = None, url_substring: Optional[str] = None) -> bool:
    """Check whether a lifecycle/review entry already has data from a given source.

    marker_field: a field name that, if present and non-empty, counts as "already done"
    (used for Wikipedia, which has its own dedicated fields).
    url_substring: a substring to look for in _meta.source_urls (used for RHS).
    """
    if marker_field is not None:
        return bool(str(entry.get(marker_field, "")).strip())
    if url_substring is not None:
        urls = entry.get("_meta", {}).get("source_urls", [])
        return any(url_substring in u for u in urls)
    return False


def has_rhs_source(entry: dict) -> bool:
    return has_source_marker(entry, url_substring="rhs.org.uk")


def has_wikipedia_source(entry: dict) -> bool:
    return has_source_marker(entry, marker_field="wikipedia_summary")


def has_pph_source(entry: dict) -> bool:
    return has_source_marker(entry, marker_field="pph_toxicity_note")


SOURCE_INFO = {
    "rhs": {
        "label": "RHS horticulture (sun/soil/hardiness/size/habit/foliage)",
        "target_file": LIFECYCLE_HARDINESS_PATH,
        "has_source": has_rhs_source,
    },
    "wikipedia": {
        "label": "Wikipedia descriptions (plain-text summary + native range, no browser needed)",
        "target_file": LIFECYCLE_HARDINESS_PATH,
        "has_source": has_wikipedia_source,
    },
    "pph": {
        "label": "Pet Poison Helpline (review-queue-only toxicity notes; never changes live safety_status)",
        "target_file": REVIEW_QUEUE_PATH,
        "has_source": has_pph_source,
    },
}


def select_plants(all_plants: list[dict], target_entries: dict, args: argparse.Namespace) -> list[dict]:
    """Apply --plant-id / --redo-all / --batch-size / --limit filters, in that order."""
    plants = all_plants
    if args.plant_id:
        plants = [item for item in plants if item.get("id") == args.plant_id]
        return plants

    has_source = SOURCE_INFO[args.source]["has_source"]
    if not args.redo_all:
        plants = [
            item for item in plants
            if not has_source(target_entries.get(str(item.get("id", "")).strip(), {}))
        ]

    if args.batch_size is not None:
        plants = plants[: max(0, args.batch_size)]
    elif args.limit is not None:
        plants = plants[: max(0, args.limit)]
    return plants


def count_remaining(source: str) -> int:
    catalogue = load_json(DOG_SAFE_PLANTS_PATH, {"plants": []})
    all_plants = catalogue.get("plants", [])
    target_data = load_json(SOURCE_INFO[source]["target_file"], {"plants": []} if source == "pph" else {"plants": {}})
    target_entries = _target_entries_by_plant_id(target_data, source)
    has_source = SOURCE_INFO[source]["has_source"]
    return len([p for p in all_plants if not has_source(target_entries.get(str(p.get("id", "")).strip(), {}))])


def _target_entries_by_plant_id(target_data: dict, source: str) -> dict:
    """Return a {plant_id: entry} view of the target file regardless of its shape.

    The lifecycle file stores plants as a dict keyed by id; the review queue stores
    plants as a list of dicts each with an "id" field. This normalizes both to a dict
    for lookups without needing to know the underlying storage shape everywhere else.
    """
    if source == "pph":
        return {str(item.get("id", "")).strip(): item for item in target_data.get("plants", [])}
    return target_data.get("plants", {})


def run_menu(_unused_total: int = 0) -> argparse.Namespace:
    """Interactive menu shown when the script is run with no arguments."""
    print("=" * 60)
    print("Plant Data Harvester - interactive setup")
    print("Dog-Safe Garden Plants | Developed by Riptide (github.com/28Riptide12)")
    print("=" * 60)
    print("Which data source do you want to gather from?")
    source_keys = list(SOURCE_INFO.keys())
    for index, key in enumerate(source_keys, start=1):
        remaining = count_remaining(key)
        print(f"  {index}) {SOURCE_INFO[key]['label']}  [{remaining} plants remaining]")
    source_choice = input(f"Choose 1-{len(source_keys)} [default 1]: ").strip() or "1"
    try:
        source = source_keys[int(source_choice) - 1]
    except (ValueError, IndexError):
        source = source_keys[0]

    total_remaining = count_remaining(source)
    print()
    print(f"Source: {SOURCE_INFO[source]['label']}")
    print(f"Plants still needing this data: {total_remaining}")
    print()
    print("How many plants should this run process?")
    print("  1) Small batch (25 plants)")
    print("  2) Medium batch (100 plants)")
    print("  3) Large batch (250 plants)")
    print(f"  4) Everything remaining ({total_remaining} plants)")
    print("  5) Custom number")
    choice = input("Choose 1-5 [default 2]: ").strip() or "2"
    batch_map = {"1": 25, "2": 100, "3": 250, "4": total_remaining}
    if choice in batch_map:
        batch_size = batch_map[choice]
    else:
        try:
            batch_size = int(input("Enter batch size: ").strip())
        except ValueError:
            batch_size = 100

    print()
    workers_raw = input("How many pages to fetch in parallel? [default 8, try 12-16 for faster] : ").strip()
    try:
        workers = int(workers_raw) if workers_raw else 8
    except ValueError:
        workers = 8

    print()
    delay_raw = input("Delay between requests per worker, in seconds [default 0.2] : ").strip()
    try:
        delay = float(delay_raw) if delay_raw else 0.2
    except ValueError:
        delay = 0.2

    print()
    print(f"Starting: source={source}, batch_size={batch_size}, workers={workers}, delay={delay}s")
    print("(Press P anytime to pause/resume, Q to quit and save progress.)")
    print()

    return argparse.Namespace(
        limit=None, plant_id=None, batch_size=batch_size, workers=workers,
        delay=delay, dry_run=False, save_every=10, redo_all=False, source=source,
    )


async def process_plant(
    source: str,
    context: BrowserContext,
    plant: dict,
    target_entries: dict,
    lock: asyncio.Lock,
    controller: KeyboardController,
    delay: float,
) -> tuple[str, str, list[str], bool]:
    """Fetch + parse one plant from the selected source and merge results.

    Returns (plant_id, name, filled_fields, matched). "matched" means a detail page/record
    was found at all, even if every relevant field was already present (nothing new to fill).
    """
    plant_id = str(plant.get("id", "")).strip()
    name = str(plant.get("name", "")).strip()
    scientific_name = str(plant.get("scientific_name", "")).strip()
    unknown_names = {"not listed", "none listed", "n/a", "unknown"}
    if not plant_id:
        return plant_id, name, [], False

    if source == "rhs":
        if (not scientific_name or scientific_name.casefold() in unknown_names) and not name:
            return plant_id, name, [], False
        detail_url = await find_rhs_detail_url(context, scientific_name, name)
        if delay:
            await asyncio.sleep(delay)
        if not detail_url:
            return plant_id, name, [], False
        facts = await parse_rhs_detail(context, detail_url)
        if delay:
            await asyncio.sleep(delay)
        async with lock:
            entry = target_entries.setdefault(plant_id, {})
            meta = entry.setdefault("_meta", {"updated_at": None, "source_urls": [], "field_sources": {}})
            filled_fields = []
            for field, value in facts.items():
                if not str(entry.get(field, "")).strip() and value:
                    entry[field] = value
                    meta["field_sources"][field] = detail_url
                    filled_fields.append(field)
            if detail_url not in meta.get("source_urls", []):
                meta.setdefault("source_urls", []).append(detail_url)
            meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return plant_id, name, filled_fields, True

    if source == "wikipedia":
        facts = await fetch_wikipedia_summary(scientific_name, name)
        if delay:
            await asyncio.sleep(delay)
        if not facts:
            return plant_id, name, [], False
        source_url = facts.get("wikipedia_url", "")
        async with lock:
            entry = target_entries.setdefault(plant_id, {})
            meta = entry.setdefault("_meta", {"updated_at": None, "source_urls": [], "field_sources": {}})
            filled_fields = []
            for field, value in facts.items():
                if field == "wikipedia_url":
                    continue
                if not str(entry.get(field, "")).strip() and value:
                    entry[field] = value
                    meta["field_sources"][field] = source_url
                    filled_fields.append(field)
            if source_url and source_url not in meta.get("source_urls", []):
                meta.setdefault("source_urls", []).append(source_url)
            meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return plant_id, name, filled_fields, True

    if source == "pph":
        detail_url = await find_pph_detail_url(context, name, scientific_name)
        if delay:
            await asyncio.sleep(delay)
        if not detail_url:
            return plant_id, name, [], False
        facts = await parse_pph_detail(context, detail_url)
        if delay:
            await asyncio.sleep(delay)
        if not facts:
            return plant_id, name, [], True
        async with lock:
            existing = target_entries.get(plant_id)
            filled_fields = []
            if existing is None or not str(existing.get("pph_toxicity_note", "")).strip():
                new_entry = {
                    "id": plant_id,
                    "name": name,
                    "scientific_name": scientific_name,
                    "safety_status": plant.get("safety_status", ""),
                    "pph_toxicity_note": facts.get("pph_toxicity_note", ""),
                    "pph_source_url": facts.get("pph_source_url", detail_url),
                    "source_name": "Pet Poison Helpline",
                    "source_status": "Unreviewed broader-source candidate. Cross-check against live safety_status before any catalogue change.",
                    "audit_status": "pending",
                    "audit_history": [{
                        "status": "pending",
                        "performed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "note": "Auto-added from Pet Poison Helpline harvest. Never promoted to the live catalogue automatically.",
                    }],
                }
                target_entries[plant_id] = new_entry
                filled_fields = ["pph_toxicity_note"]
        return plant_id, name, filled_fields, True

    return plant_id, name, [], False



async def run_harvest(args: argparse.Namespace) -> dict:
    source = args.source
    target_file = SOURCE_INFO[source]["target_file"]
    catalogue = load_json(DOG_SAFE_PLANTS_PATH, {"plants": []})
    all_plants = catalogue.get("plants", [])

    if source == "pph":
        target_data = load_json(target_file, {
            "source": "Pet Poison Helpline",
            "generated_at": None,
            "plants": [],
            "audit_log": [],
        })
        target_data.setdefault("plants", [])
        target_entries = _target_entries_by_plant_id(target_data, source)
    else:
        target_data = load_json(target_file, {
            "version": "1.0", "generated_at": None,
            "description": "Per-plant lifecycle, hardiness, sowing, and winter-handling facts with provenance.",
            "plants": {},
        })
        target_entries = target_data.setdefault("plants", {})

    plants = select_plants(all_plants, target_entries, args)
    if not plants:
        print(f"Nothing to do: all plants already have {source} data (or filters matched none). Use --redo-all to refetch.")
        return {"processed": 0, "updated": 0, "no_match": 0, "no_new_data": 0, "field_counts": {}, "elapsed": 0.0, "quit_early": False, "source": source}

    def save_progress() -> None:
        if args.dry_run:
            return
        target_data["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if source == "pph":
            target_data["plants"] = list(target_entries.values())
        write_json(target_file, target_data)

    controller = KeyboardController()
    controller.start()

    total_plants = len(plants)
    start_time = time.monotonic()
    updated_count = 0
    no_match_count = 0
    no_new_data_count = 0
    field_counts: dict[str, int] = {}
    updated_names: list[str] = []
    processed_count = 0
    lock = asyncio.Lock()
    queue: asyncio.Queue = asyncio.Queue()
    for plant in plants:
        queue.put_nowait(plant)

    print(f"Processing {total_plants} plants from {source} with {args.workers} parallel workers...\n")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()

        async def worker() -> None:
            nonlocal updated_count, processed_count, no_match_count, no_new_data_count
            while True:
                await controller.wait_while_paused()
                if controller.quit_requested:
                    return
                try:
                    plant = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

                plant_id, name, filled_fields, matched = await process_plant(
                    source, context, plant, target_entries, lock, controller, args.delay
                )
                async with lock:
                    processed_count += 1
                    elapsed = time.monotonic() - start_time
                    rate = processed_count / elapsed if elapsed > 0 else 0
                    remaining = total_plants - processed_count
                    eta_seconds = remaining / rate if rate > 0 else 0
                    progress_suffix = (
                        f"  [{processed_count}/{total_plants} | elapsed {format_duration(elapsed)} "
                        f"| ETA {format_duration(eta_seconds)} | {rate:.2f} plants/sec]"
                    )
                    if filled_fields:
                        updated_count += 1
                        updated_names.append(name or plant_id)
                        for field in filled_fields:
                            field_counts[field] = field_counts.get(field, 0) + 1
                        print(f"{name} ({plant_id}): filled {', '.join(filled_fields)}{progress_suffix}")
                    elif plant_id and matched:
                        no_new_data_count += 1
                        print(f"{name} ({plant_id}): no new data{progress_suffix}")
                    elif plant_id:
                        no_match_count += 1
                        print(f"{name} ({plant_id}): no {source} match found{progress_suffix}")
                    if args.save_every and processed_count % args.save_every == 0:
                        save_progress()
                        print(f"  (autosaved: {updated_count} plants updated so far)")

        try:
            workers = [asyncio.create_task(worker()) for _ in range(max(1, args.workers))]
            await asyncio.gather(*workers)
        except KeyboardInterrupt:
            print("\nInterrupted by Ctrl+C - saving progress made so far.")
        finally:
            controller.stop()
            await context.close()
            await browser.close()

    total_elapsed = time.monotonic() - start_time
    if controller.quit_requested:
        print(f"\nStopped early by user after {processed_count}/{total_plants} plants.")

    if not args.dry_run:
        save_progress()

    remaining_after = len(select_plants(all_plants, target_entries, argparse.Namespace(
        plant_id=None, redo_all=False, batch_size=None, limit=None, source=source,
    )))

    return {
        "processed": processed_count,
        "updated": updated_count,
        "no_match": no_match_count,
        "no_new_data": no_new_data_count,
        "field_counts": field_counts,
        "updated_names": updated_names,
        "elapsed": total_elapsed,
        "quit_early": controller.quit_requested,
        "dry_run": args.dry_run,
        "remaining_after": remaining_after,
        "source": source,
    }


def print_summary(stats: dict) -> None:
    """Print an in-depth end-of-run summary: totals, per-field breakdown, and remaining work."""
    source = stats.get("source", "rhs")
    print()
    print("=" * 60)
    print(f"BATCH SUMMARY ({source})")
    print("=" * 60)
    if stats["processed"] == 0:
        print("No plants were processed this run.")
        print("=" * 60)
        return

    print(f"Plants processed:        {stats['processed']}")
    print(f"  - updated with data:   {stats['updated']}")
    print(f"  - matched, no gaps:    {stats['no_new_data']}  (page found, but fields already filled)")
    print(f"  - no {source} match found:  {stats['no_match']}")
    print(f"Time taken:              {format_duration(stats['elapsed'])}")
    if stats["processed"] and stats["elapsed"] > 0:
        print(f"Average rate:            {stats['processed'] / stats['elapsed']:.2f} plants/sec")
    if stats["quit_early"]:
        print("Note: this batch was stopped early by user request (Q). Progress up to that point is saved.")

    field_counts = stats.get("field_counts", {})
    if field_counts:
        print()
        print("Fields filled (count of plants where this field was newly added):")
        for field, count in sorted(field_counts.items(), key=lambda kv: -kv[1]):
            print(f"  - {field:<18} {count}")

    updated_names = stats.get("updated_names", [])
    if updated_names:
        print()
        preview = updated_names[:15]
        print(f"Plants updated this run ({len(updated_names)} total):")
        print("  " + ", ".join(preview) + (", ..." if len(updated_names) > len(preview) else ""))

    if source == "pph":
        print()
        print("Reminder: Pet Poison Helpline notes are review-queue-only candidates.")
        print("Nothing was written to the live safe-plant catalogue or its safety_status field.")

    if stats.get("dry_run"):
        print()
        print("This was a DRY RUN - no files were written.")
    else:
        print()
        print(f"Plants still needing {source} data across the whole catalogue: {stats.get('remaining_after', '?')}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=str, default="rhs", choices=list(SOURCE_INFO.keys()), help="Which data source to harvest from")
    parser.add_argument("--limit", type=int, default=None, help="Harvest only the first N selected plants")
    parser.add_argument("--batch-size", type=int, default=None, help="Process only this many not-yet-done plants, then stop (resumable)")
    parser.add_argument("--plant-id", type=str, default=None, help="Harvest only this single plant id")
    parser.add_argument("--workers", type=int, default=8, help="Number of plants to fetch concurrently (default 8; try 12-16 for more speed)")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay per worker between requests (seconds)")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing")
    parser.add_argument("--save-every", type=int, default=10, help="Autosave progress to disk every N plants (0 disables autosave)")
    parser.add_argument("--redo-all", action="store_true", help="Ignore already-harvested plants and refetch everything selected")
    args = parser.parse_args()

    if len(sys.argv) > 1:
        # Scripted/one-shot invocation with explicit flags: run once and exit.
        stats = asyncio.run(run_harvest(args))
        print_summary(stats)
        return

    # No arguments: interactive menu that loops until the user chooses to exit,
    # so you can run several batches back-to-back without relaunching the window.
    while True:
        menu_args = run_menu()
        if count_remaining(menu_args.source) == 0 and not menu_args.redo_all:
            print(f"All plants already have {menu_args.source} data. Nothing left to harvest (use --redo-all to refetch).")
        else:
            stats = asyncio.run(run_harvest(menu_args))
            print_summary(stats)

        print()
        again = input("Run another batch? [Y/n] : ").strip().lower()
        if again in {"n", "no", "q", "quit", "exit"}:
            print("Done for now. Run this script again any time to continue.")
            break
        print()


if __name__ == "__main__":
    main()


