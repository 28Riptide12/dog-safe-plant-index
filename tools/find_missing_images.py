#!/usr/bin/env python3
"""
Find and update missing plant images from Wikimedia Commons.
Prioritizes plants with placeholder images and searches for real photos.
"""

import json
import argparse
import re
import requests
import time
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"

PLACEHOLDER_PATTERNS = [
    r'noimage',
    r'imageunavailable',
    r'\/image(?:_0)?\.jpg',
    r'\/static\/placeholders\/',
    r'^$',  # empty
]

def is_placeholder(image_url: str) -> bool:
    """Check if image URL is a placeholder."""
    if not image_url or not image_url.strip():
        return True
    return any(re.search(pattern, image_url, re.I) for pattern in PLACEHOLDER_PATTERNS)

def search_commons_for_plant(plant_name: str, scientific_name: str, max_retries: int = 3) -> Optional[dict]:
    """
    Search Wikimedia Commons for a plant image.
    Returns the best matching image dict or None.
    Includes exponential backoff for rate limiting.
    """
    search_term = scientific_name if scientific_name else plant_name
    
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
                    "gsrlimit": 10,
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "iiurlwidth": 600,
                    "format": "json"
                },
                headers={"User-Agent": "TopsoilPlantGuide/1.0"},
                timeout=15
            )
            
            # Handle rate limiting with backoff
            if response.status_code == 429:
                if attempt < max_retries - 1:
                    wait_time = 2 ** (attempt + 1)
                    print(f"  [Rate limited] Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"  Skipped: Commons rate limiting")
                    return None
            
            response.raise_for_status()
            
            pages = response.json().get("query", {}).get("pages", {}).values()
            
            # Filter by scientific name tokens if available
            if scientific_name:
                tokens = [t.lower() for t in re.findall(r"[a-z]+", scientific_name) if len(t) > 2]
                matches = [
                    page for page in pages
                    if all(token in page.get("title", "").lower() for token in tokens)
                    and page.get("imageinfo")
                ]
            else:
                matches = [p for p in pages if p.get("imageinfo")]
            
            if not matches:
                return None
            
            # Return best match
            best = matches[0]
            info = best["imageinfo"][0]
            return {
                "image_url": info.get("thumburl") or info.get("url"),
                "image_source_url": info.get("descriptionurl") or 
                                  f"https://commons.wikimedia.org/wiki/{best.get('title', '').replace(' ', '_')}",
                "title": best.get("title", ""),
                "confidence": "high"
            }
        
        except requests.RequestException as e:
            if attempt < max_retries - 1 and "429" in str(e):
                continue
            print(f"  Error searching Commons: {e}")
            return None
        except (KeyError, IndexError) as e:
            print(f"  Error parsing Commons response: {e}")
            return None
    
    return None

def find_plants_needing_images(database: dict) -> list[dict]:
    """
    Find all plants with missing or placeholder images.
    Returns list of plants sorted by priority.
    """
    plants = database.get("plants", [])
    needs_images = [
        plant for plant in plants
        if is_placeholder(plant.get("image_url", ""))
    ]
    
    # Sort by category priority
    priority = {"flowers": 0, "vegetables": 1, "herbs": 2, "fruit": 3, "grasses": 4}
    return sorted(
        needs_images,
        key=lambda p: (priority.get(p.get("category", ""), 999), p.get("name", ""))
    )

def update_plant_image(database: dict, plant_id: str, image_url: str, image_source_url: str) -> bool:
    """Update a plant's image in the database."""
    for plant in database.get("plants", []):
        if plant.get("id") == plant_id:
            plant["image_url"] = image_url
            plant["image_source_url"] = image_source_url
            return True
    return False

def main():
    parser = argparse.ArgumentParser(
        description="Find and update missing plant images from Wikimedia Commons"
    )
    parser.add_argument(
        "--max-plants",
        type=int,
        default=20,
        help="Maximum number of plants to update (default: 20)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be updated without saving"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between Commons API requests in seconds (default: 1.0)"
    )
    
    args = parser.parse_args()
    
    # Load plant database
    if not DOG_SAFE_PLANTS_PATH.exists():
        print(f"Error: Plant database not found at {DOG_SAFE_PLANTS_PATH}")
        return 1
    
    with open(DOG_SAFE_PLANTS_PATH, 'r', encoding='utf-8') as f:
        database = json.load(f)
    
    # Find plants needing images
    plants_to_fix = find_plants_needing_images(database)
    
    if not plants_to_fix:
        print("[OK] All plants have images!")
        return 0
    
    print(f"Found {len(plants_to_fix)} plants needing images")
    print(f"Will update up to {args.max_plants} plants\n")
    
    updated_count = 0
    skipped_count = 0
    
    for plant in plants_to_fix[:args.max_plants]:
        plant_id = plant.get("id", "")
        plant_name = plant.get("name", "")
        scientific_name = plant.get("scientific_name", "")
        
        print(f"-> {plant_name} ({scientific_name})", end=" ")
        
        # Search for image
        result = search_commons_for_plant(plant_name, scientific_name)
        
        if result:
            print(f"[FOUND] {result['title']}")
            
            if args.dry_run:
                print(f"  [DRY RUN] Would update to: {result['image_url']}")
            else:
                if update_plant_image(database, plant_id, result["image_url"], result["image_source_url"]):
                    updated_count += 1
                else:
                    print(f"  Error: Could not find plant {plant_id}")
                    skipped_count += 1
        else:
            print("[NOT FOUND]")
            skipped_count += 1
        
        # Rate limiting
        time.sleep(args.delay)
    
    # Save database
    if updated_count > 0 and not args.dry_run:
        # Backup
        backup_path = DOG_SAFE_PLANTS_PATH.with_suffix(".backup.json")
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2)
        print(f"\n[OK] Saved backup to {backup_path.name}")
        
        # Save updated database
        with open(DOG_SAFE_PLANTS_PATH, 'w', encoding='utf-8') as f:
            json.dump(database, f, indent=2)
        print(f"[OK] Updated {updated_count} plant images in {DOG_SAFE_PLANTS_PATH.name}")
    
    print(f"\nSummary: {updated_count} updated, {skipped_count} skipped")
    return 0 if updated_count > 0 else 1

if __name__ == "__main__":
    exit(main())
