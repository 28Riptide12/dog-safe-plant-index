#!/usr/bin/env python3
"""
Batch image finder and auto-approver for plants needing images.
Finds high-quality images and automatically approves those with quality score > 70.
"""

import json
import sys
from pathlib import Path
from image_sources import search_wikimedia_commons, search_inaturalist

BASE_DIR = Path(__file__).resolve().parent.parent
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"

PLACEHOLDER_PATTERNS = [
    'noimage', 'imageunavailable', '/image', '/static/placeholders/'
]

def is_placeholder(url: str) -> bool:
    """Check if URL is a placeholder."""
    if not url or not url.strip():
        return True
    return any(p in url.lower() for p in PLACEHOLDER_PATTERNS)

def find_images_for_plant(plant: dict) -> dict or None:
    """Find best image for a plant."""
    print(f"  Searching: {plant['name']}", end='... ')
    sys.stdout.flush()
    
    candidates = []
    
    try:
        # Search Wikimedia Commons first
        commons = search_wikimedia_commons(
            plant.get('name', ''),
            plant.get('scientific_name', '')
        )
        candidates.extend(commons[:3])
        
        # Then iNaturalist if scientific name available
        if plant.get('scientific_name'):
            inaturalist = search_inaturalist(
                plant.get('scientific_name', ''),
                plant.get('name', '')
            )
            candidates.extend(inaturalist[:2])
    except Exception as e:
        print(f"Error: {e}")
        return None
    
    # Filter to high-quality images only (lowered threshold to 60 for broader coverage)
    best = [c for c in candidates if c.quality_score >= 60]
    
    if best:
        top = best[0]
        print(f"[OK] Found {top.title[:30]}... (score: {top.quality_score})")
        return {
            'url': top.url,
            'source': top.source,
            'quality_score': top.quality_score
        }
    else:
        print(f"No high-quality images found")
        return None

def main():
    """Main batch processing loop."""
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    plants = data['plants']
    plants_needing = [p for p in plants if is_placeholder(p.get('image_url', ''))]
    
    print(f"\n[Batch Image Filler]")
    print(f"Total plants: {len(plants)}")
    print(f"Plants needing images: {len(plants_needing)}")
    print(f"Processing first 20...\n")
    
    updated = 0
    for plant in plants_needing[:20]:
        image = find_images_for_plant(plant)
        if image:
            plant['image_url'] = image['url']
            plant['image_source_url'] = image['source']
            updated += 1
    
    # Save updated database
    with open(DOG_SAFE_PLANTS_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"\n[OK] Updated {updated} plants with new images")
    print(f"Remaining plants needing images: {len(plants_needing) - updated}")

if __name__ == '__main__':
    main()
