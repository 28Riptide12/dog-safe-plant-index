#!/usr/bin/env python3
"""
Enrich plant database with RHS UK hardiness zones based on plant characteristics.
Hardiness zones: H1a/H1b (half-hardy), H2 (frost-hardy), H3-H7 (hardy), H8 (very hardy).
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
PLANTS_FILE = REPO_ROOT / "database" / "dog_safe_plants.json"

# Hardiness zone assignments based on plant type, origin, and characteristics
HARDINESS_RULES = {
    # Herbaceous plants and perennials - generally hardy
    "sunflower": "H3-H7",
    "rose": "H3-H7",
    "daisy": "H4-H7",
    "lavender": "H3-H7",
    "sage": "H4-H7",
    "basil": "H1a",  # Annual, frost-tender
    "mint": "H3-H7",
    "thyme": "H3-H7",
    "rosemary": "H3-H4",
    "parsley": "H3-H7",
    "dill": "H2-H7",  # Hardy annual
    "fennel": "H2-H7",
    "chives": "H4-H7",
    "coriander": "H1a",  # Tender annual
    
    # Vegetables - mostly hardy annuals
    "carrot": "H2-H7",
    "beetroot": "H2-H7",
    "lettuce": "H2-H7",
    "spinach": "H2-H7",
    "pea": "H2-H7",
    "bean": "H1a-H2",  # Tender annuals
    "broccoli": "H2-H7",
    "cabbage": "H2-H7",
    "celery": "H2-H7",
    "cucumber": "H1a",
    "courgette": "H1a",
    "squash": "H1a",
    "pumpkin": "H1a",
    "tomato": "H1a",
    "pepper": "H1a",
    "potato": "H2-H7",
    "onion": "H2-H7",
    "garlic": "H2-H7",
    "leek": "H2-H7",
    
    # Fruits - varied hardiness
    "apple": "H4-H7",
    "pear": "H4-H7",
    "plum": "H4-H7",
    "cherry": "H4-H7",
    "strawberry": "H3-H7",
    "raspberry": "H3-H7",
    "blackberry": "H3-H7",
    "blueberry": "H4-H7",
    "currant": "H4-H7",
    "gooseberry": "H4-H7",
    
    # Tender plants and house plants
    "begonia": "H1a-H1b",
    "geranium": "H2-H3",  # Tender perennial
    "fuchsia": "H2-H3",
    "impatiens": "H1a",
    "petunia": "H1a",
    "zinnia": "H1a",
    "marigold": "H1a",
    "nasturtium": "H1a",
    "hibiscus": "H1a-H2",
    "bougainvillea": "H1a",
    
    # Hardy flowers
    "snapdragon": "H2-H7",  # Hardy annual
    "pansy": "H2-H7",
    "viola": "H2-H7",
    "poppy": "H2-H7",
    "cornflower": "H2-H7",
    "foxglove": "H3-H7",
    "delphinium": "H3-H7",
    "hollyhock": "H3-H7",
    "aquilegia": "H3-H7",
    "astilbe": "H4-H7",
    "coneflower": "H3-H7",
    "helenium": "H3-H7",
    "heuchera": "H3-H7",
    "hosta": "H4-H7",
    "peony": "H4-H7",
    "sedum": "H4-H7",
    
    # Grasses
    "fescue": "H3-H7",
    "oat grass": "H3-H7",
    "fountain grass": "H2-H3",
    "blood grass": "H3-H7",
    
    # Trees (mostly hardy)
    "maple": "H3-H7",
    "oak": "H4-H7",
    "birch": "H4-H7",
    "ash": "H4-H7",
    "elm": "H4-H7",
    "hawthorn": "H4-H7",
}

def get_hardiness_zone(plant_name: str, category: str) -> str:
    """Determine hardiness zone for a plant based on name and category."""
    name_lower = plant_name.lower()
    
    # Check if plant name contains any hardiness zone keywords
    for keyword, zone in HARDINESS_RULES.items():
        if keyword in name_lower:
            return zone
    
    # Default hardiness zones by category if no keyword match
    category_defaults = {
        "flowers": "H2-H7",
        "vegetables": "H2-H7",
        "fruit": "H3-H7",
        "herbs": "H2-H7",
        "grasses": "H3-H7",
        "houseplants": "H1a-H1b",
    }
    
    return category_defaults.get(category.lower(), "H2-H7")

def enrich_plants() -> dict:
    """Add hardiness zones to all plants in the database."""
    with open(PLANTS_FILE, encoding="utf-8") as f:
        data = json.load(f)
    
    plants = data.get("plants", [])
    enriched_count = 0
    
    for plant in plants:
        if "hardiness_zones_uk" not in plant:
            zone = get_hardiness_zone(plant.get("name", ""), plant.get("category", ""))
            plant["hardiness_zones_uk"] = zone
            enriched_count += 1
        
        # Also add hardiness info metadata if missing
        if "hardiness_info" not in plant:
            zone = plant.get("hardiness_zones_uk", "")
            plant["hardiness_info"] = {
                "zones_uk": zone,
                "min_temp_c": get_min_temp(zone),
                "max_temp_c": 40,  # Most plants don't survive above this
            }
    
    # Write back to file
    with open(PLANTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    return {
        "enriched": enriched_count,
        "total": len(plants),
        "file": str(PLANTS_FILE),
    }

def get_min_temp(zone: str) -> int:
    """Get approximate minimum winter temperature (°C) for a hardiness zone."""
    zone_temps = {
        "H1a": 15,
        "H1b": 10,
        "H2": 5,
        "H3": 0,
        "H4": -5,
        "H5": -10,
        "H6": -15,
        "H7": -20,
    }
    
    # Handle ranges like "H2-H7" by taking the lower value
    if "-" in zone:
        first_zone = zone.split("-")[0].strip()
    else:
        first_zone = zone.strip()
    
    return zone_temps.get(first_zone, 0)

if __name__ == "__main__":
    try:
        result = enrich_plants()
        print(f"SUCCESS: Enriched {result['enriched']} plants with hardiness zones")
        print(f"  Total plants: {result['total']}")
        print(f"  File: {result['file']}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
