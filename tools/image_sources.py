#!/usr/bin/env python3
"""
Multi-source plant image finder with quality scoring.
Searches Wikimedia Commons and iNaturalist for high-quality plant images.
Includes image quality evaluation and batch processing.
"""

import json
import requests
import time
import re
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent.parent
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
IMAGE_CACHE_PATH = BASE_DIR / "database" / "image_cache.json"

PLACEHOLDER_PATTERNS = [
    r'noimage',
    r'imageunavailable',
    r'\/image(?:_0)?\.jpg',
    r'\/static\/placeholders\/',
    r'^$',  # empty
]

@dataclass
class ImageCandidate:
    """Represents an image candidate for a plant."""
    url: str
    source: str  # 'commons', 'inaturalist', 'local'
    title: str
    quality_score: float  # 0-100
    resolution: Tuple[int, int]  # (width, height)
    license: str
    attribution: str
    
    def to_dict(self):
        return {
            'url': self.url,
            'source': self.source,
            'title': self.title,
            'quality_score': self.quality_score,
            'resolution': self.resolution,
            'license': self.license,
            'attribution': self.attribution,
        }

def is_placeholder(image_url: str) -> bool:
    """Check if image URL is a placeholder."""
    if not image_url or not image_url.strip():
        return True
    return any(re.search(pattern, image_url, re.I) for pattern in PLACEHOLDER_PATTERNS)

def calculate_image_quality_score(
    resolution: Tuple[int, int],
    has_exif: bool = False,
    view_count: int = 0,
    license_type: str = 'CC0',
    is_professional: bool = False
) -> float:
    """
    Calculate image quality score (0-100).
    Factors:
    - Resolution: 600x600+ is ideal (50 points max)
    - Clarity/focus: Estimated from EXIF (20 points max)
    - Popularity: View count indicates quality (15 points max)
    - License: CC0 > CC-BY > CC-BY-SA > Others (10 points max)
    - Professional: Camera vs. phone (5 points max)
    """
    score = 0
    
    # Resolution scoring (50 points max)
    width, height = resolution
    min_dim = min(width, height)
    if min_dim >= 1200:
        score += 50
    elif min_dim >= 800:
        score += 40
    elif min_dim >= 600:
        score += 30
    elif min_dim >= 400:
        score += 20
    else:
        score += 10
    
    # Clarity/focus (20 points)
    if has_exif:
        score += 20
    
    # Popularity (15 points max)
    if view_count > 10000:
        score += 15
    elif view_count > 1000:
        score += 10
    elif view_count > 100:
        score += 5
    
    # License (10 points max)
    if license_type.upper() == 'CC0':
        score += 10
    elif 'CC-BY' in license_type.upper():
        score += 8
    elif 'CC-BY-SA' in license_type.upper():
        score += 6
    else:
        score += 3
    
    # Professional (5 points)
    if is_professional:
        score += 5
    
    return min(score, 100)

def search_wikimedia_commons(plant_name: str, scientific_name: str, max_retries: int = 3) -> List[ImageCandidate]:
    """
    Search Wikimedia Commons for plant images.
    Returns list of ImageCandidate objects sorted by quality.
    """
    search_term = scientific_name if scientific_name else plant_name
    candidates = []
    headers = {'User-Agent': 'PlantCatalogApp/1.0 (https://github.com/example/plant-catalog)'}
    
    for attempt in range(max_retries):
        try:
            # Search Commons
            response = requests.get(
                "https://commons.wikimedia.org/w/api.php",
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrsearch": search_term,
                    "gsrnamespace": 6,  # File namespace
                    "gsrlimit": 20,
                    "prop": "imageinfo",
                    "iiprop": "url|size",
                    "format": "json",
                },
                headers=headers,
                timeout=10
            )
            
            if response.status_code == 429:  # Rate limited
                wait_time = (2 ** attempt)
                print(f"  Rate limited, waiting {wait_time}s...")
                time.sleep(wait_time)
                continue
            
            response.raise_for_status()
            data = response.json()
            
            if "batchcomplete" in data:
                pages = data.get("query", {}).get("pages", {})
                
                for page_id, page_data in pages.items():
                    if "imageinfo" in page_data:
                        image_info = page_data["imageinfo"][0]
                        url = image_info.get("url", "")
                        
                        # Skip videos and non-image files
                        if not url or any(url.endswith(ext) for ext in ['.webm', '.ogv', '.mp4']):
                            continue
                        
                        title = page_data.get("title", "").replace("File:", "")
                        width = image_info.get("width", 0)
                        height = image_info.get("height", 0)
                        
                        # Quality score
                        quality = calculate_image_quality_score(
                            resolution=(width, height),
                            license_type='CC0'  # Commons files are public domain
                        )
                        
                        candidates.append(ImageCandidate(
                            url=url,
                            source='commons',
                            title=title,
                            quality_score=quality,
                            resolution=(width, height),
                            license='CC0',
                            attribution=f"Wikimedia Commons - {title}"
                        ))
            
            break  # Success, exit retry loop
            
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt)
                time.sleep(wait_time)
        except Exception as e:
            print(f"  Commons search error: {e}")
    
    return sorted(candidates, key=lambda x: x.quality_score, reverse=True)

def search_openverse(plant_name: str, scientific_name: str, max_results: int = 10) -> List[ImageCandidate]:
    """Search Openverse for CC-licensed plant photos."""
    candidates = []
    query = scientific_name or plant_name
    if not query:
        return candidates

    try:
        response = requests.get(
            "https://api.openverse.org/v1/images/",
            params={
                "q": query,
                "page_size": max_results,
                "license_type": "all-cc",
                "page": 1,
            },
            headers={'User-Agent': 'PlantCatalogApp/1.0 (https://github.com/example/plant-catalog)'},
            timeout=10,
        )
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type", "") or "").lower()
        if "application/json" not in content_type and "json" not in content_type:
            preview = re.sub(r"\s+", " ", response.text or "")[:180]
            raise ValueError(f"Openverse API returned non-JSON content for '{query}': {preview}")
        payload = response.json()
        for result in payload.get("results", [])[:max_results]:
            image_url = str(result.get("url") or result.get("thumbnail") or "").strip()
            if not image_url.startswith("http"):
                continue
            width = int(result.get("width") or 1024)
            height = int(result.get("height") or 768)
            license_name = str(result.get("license") or "CC0").strip() or "CC0"
            quality = calculate_image_quality_score(
                resolution=(width, height),
                license_type=license_name,
                is_professional=bool(result.get("creator")),
            )
            title = str(result.get("title") or scientific_name or plant_name or "Openverse image").strip()
            candidates.append(ImageCandidate(
                url=image_url,
                source='openverse',
                title=title,
                quality_score=quality,
                resolution=(width, height),
                license=license_name,
                attribution=f"Openverse - {title}",
            ))
    except Exception as e:
        print(f"  Openverse search error: {e}")

    return sorted(candidates, key=lambda x: x.quality_score, reverse=True)


def search_inaturalist(scientific_name: str, plant_name: str = "", max_results: int = 10) -> List[ImageCandidate]:
    """
    Search iNaturalist for plant images.
    Returns high-quality licensed images.
    """
    candidates = []
    headers = {'User-Agent': 'PlantCatalogApp/1.0 (https://github.com/example/plant-catalog)'}
    
    try:
        # iNaturalist API - search for observations
        response = requests.get(
            "https://api.inaturalist.org/v1/observations",
            params={
                "q": scientific_name,
                "taxon_name": scientific_name,
                "quality_grade": "research",  # Only research-grade observations
                "photos": True,
                "sounds": False,
                "per_page": max_results,
                "order_by": "votes",  # Most voted = best quality
            },
            headers=headers,
            timeout=10
        )
        
        response.raise_for_status()
        data = response.json()
        
        for obs in data.get("results", [])[:max_results]:
            photos = obs.get("photos", [])
            
            for photo in photos:
                # Check license
                license_code = photo.get("license_code", "")
                if not license_code or license_code not in ["cc0", "cc-by", "cc-by-nc", "cc-by-sa", "cc-by-nc-sa"]:
                    continue  # Skip proprietary licenses
                
                url = photo.get("url", "").replace("square", "large")  # Get larger version
                width = photo.get("original_dimensions", {}).get("width", 1024)
                height = photo.get("original_dimensions", {}).get("height", 768)
                
                # iNaturalist photos are generally well-curated
                quality = calculate_image_quality_score(
                    resolution=(width, height),
                    view_count=obs.get("faves_count", 0),
                    license_type=f"CC-{license_code.upper()}",
                    is_professional=True  # Community-vetted
                )
                
                observer = obs.get("user", {}).get("login", "Unknown")
                candidates.append(ImageCandidate(
                    url=url,
                    source='inaturalist',
                    title=f"{scientific_name} - {observer}",
                    quality_score=quality,
                    resolution=(width, height),
                    license=license_code.upper(),
                    attribution=f"iNaturalist - © {observer}"
                ))
        
    except Exception as e:
        print(f"  iNaturalist search error: {e}")
    
    return sorted(candidates, key=lambda x: x.quality_score, reverse=True)

def find_best_image(plant_name: str, scientific_name: str, search_both: bool = True) -> Optional[ImageCandidate]:
    """
    Find the best image for a plant from all sources.
    Returns the highest quality ImageCandidate or None.
    """
    candidates = []
    
    # Search Wikimedia Commons
    print(f"  Searching Commons for {scientific_name or plant_name}...")
    commons_results = search_wikimedia_commons(plant_name, scientific_name)
    candidates.extend(commons_results)

    # Search Openverse for additional CC-licensed photography and botanical imagery.
    print(f"  Searching Openverse for {scientific_name or plant_name}...")
    openverse_results = search_openverse(plant_name, scientific_name)
    candidates.extend(openverse_results)
    
    # Also search iNaturalist
    if search_both and scientific_name:
        print(f"  Searching iNaturalist for {scientific_name}...")
        inaturalist_results = search_inaturalist(scientific_name, plant_name)
        candidates.extend(inaturalist_results)
    
    # Return best by quality score
    if candidates:
        best = max(candidates, key=lambda x: x.quality_score)
        print(f"  Best: {best.source} ({best.quality_score:.0f}/100, {best.resolution[0]}x{best.resolution[1]})")
        return best
    
    return None

def find_multiple_images(plant_name: str, scientific_name: str, count: int = 5) -> List[ImageCandidate]:
    """
    Find multiple image candidates for a plant.
    Useful for manual curation UI.
    """
    candidates = []
    
    # Search multiple sources
    commons_results = search_wikimedia_commons(plant_name, scientific_name)
    candidates.extend(commons_results)
    candidates.extend(search_openverse(plant_name, scientific_name))
    
    if scientific_name:
        inaturalist_results = search_inaturalist(scientific_name, plant_name)
        candidates.extend(inaturalist_results)
    
    # Sort by quality and return top N
    return sorted(candidates, key=lambda x: x.quality_score, reverse=True)[:count]

def batch_find_images(max_plants: int = 10, progress_every: int = 1) -> Dict[str, dict]:
    """
    Find images for all plants needing them.
    Returns dict of plant_id -> {'image_url', 'source', 'quality_score', 'candidates'}
    """
    results = {}
    
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    plants = data.get("plants", [])
    plants_needing_images = [
        p for p in plants
        if is_placeholder(p.get("image_url", ""))
    ][:max_plants]
    
    print(f"Found {len(plants_needing_images)} plants needing images")
    
    for i, plant in enumerate(plants_needing_images):
        if i > 0 and i % progress_every == 0:
            print(f"Progress {i}/{len(plants_needing_images)}")
        
        best_image = find_best_image(
            plant.get("name"),
            plant.get("scientific_name"),
            search_both=True
        )
        
        if best_image:
            candidates = find_multiple_images(
                plant.get("name"),
                plant.get("scientific_name"),
                count=3
            )
            
            results[plant["id"]] = {
                "plant_id": plant["id"],
                "plant_name": plant.get("name"),
                "image_url": best_image.url,
                "image_source": best_image.source,
                "quality_score": best_image.quality_score,
                "resolution": best_image.resolution,
                "license": best_image.license,
                "attribution": best_image.attribution,
                "candidates": [c.to_dict() for c in candidates],
                "timestamp": datetime.now().isoformat(),
            }
        
        time.sleep(2)  # Rate limiting
    
    return results

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Find plant images from multiple sources")
    parser.add_argument("--test", action="store_true", help="Test with a single plant")
    parser.add_argument("--batch", action="store_true", help="Batch process plants")
    parser.add_argument("--max-plants", type=int, default=10, help="Max plants to process")
    parser.add_argument("--progress-every", type=int, default=1, help="Print progress every N plants")
    
    args = parser.parse_args()
    
    if args.test:
        print("Testing image finder with Tomato...")
        result = find_best_image("Tomato", "Solanum lycopersicum")
        if result:
            print(f"  Found: {result.title}")
            print(f"  Quality: {result.quality_score:.0f}/100")
            print(f"  Resolution: {result.resolution}")
    
    elif args.batch:
        print("Batch processing plants...")
        results = batch_find_images(max_plants=args.max_plants, progress_every=args.progress_every)
        
        # Save to cache
        with open(IMAGE_CACHE_PATH, 'w') as f:
            json.dump(results, f, indent=2)
        
        print(f"Saved {len(results)} results to {IMAGE_CACHE_PATH}")
