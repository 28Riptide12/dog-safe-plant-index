#!/usr/bin/env python3
"""
Add seasonality and lifecycle information to plant database.
Enriches plant data with:
- Bloom/growth seasons
- Best planting times
- Harvest season (for vegetables/fruit)
- Dormancy period
"""

import json
from pathlib import Path
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DOG_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"

# Comprehensive seasonality database
PLANT_SEASONALITY = {
    "lavender": {
        "name": "Lavender",
        "scientific_name": "Lavandula angustifolia",
        "category": "flowers",
        "safety_status": "Non-toxic to dogs",
        "image_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/181838/medium.jpg",
        "description": "Fragrant purple flowers on compact evergreen shrubs. Dog-friendly and drought-tolerant.",
        "source_url": "https://www.aspca.org/pet-care/animal-poison-control/dogs-plant-list",
        "image_source_url": "https://www.inaturalist.org/taxa/1234567",
        "hardiness_zones_uk": "H4-H7",
        "hardiness_info": {
            "zones_uk": "H4-H7",
            "min_temp_c": -10,
            "max_temp_c": 40
        },
        "seasonality": {
            "bloom_start_month": 6,  # June
            "bloom_end_month": 9,    # September
            "peak_bloom_months": [7, 8],  # July, August
            "planting_season": ["spring", "autumn"],
            "growth_habit": "Evergreen perennial",
            "dormancy_months": [],  # No dormancy - evergreen
            "harvest_season": None,  # Not edible
            "best_months_to_plant": [3, 4, 5, 9, 10, 11]  # March-May, Sept-Nov
        }
    },
    "sunflower": {
        "seasonality": {
            "bloom_start_month": 7,
            "bloom_end_month": 10,
            "peak_bloom_months": [8, 9],
            "planting_season": ["spring"],
            "growth_habit": "Annual",
            "dormancy_months": [12, 1, 2],
            "harvest_season": "autumn",
            "best_months_to_plant": [4, 5, 6]
        }
    },
    "rose": {
        "seasonality": {
            "bloom_start_month": 5,
            "bloom_end_month": 10,
            "peak_bloom_months": [6, 7, 8, 9],
            "planting_season": ["spring", "autumn"],
            "growth_habit": "Deciduous shrub",
            "dormancy_months": [11, 12, 1, 2, 3],
            "harvest_season": None,
            "best_months_to_plant": [3, 4, 10, 11]
        }
    },
    "tomato": {
        "seasonality": {
            "bloom_start_month": 6,
            "bloom_end_month": 9,
            "peak_bloom_months": [7, 8],
            "planting_season": ["spring"],
            "growth_habit": "Annual",
            "dormancy_months": [11, 12, 1, 2],
            "harvest_season": "summer",
            "best_months_to_plant": [4, 5, 6]
        }
    },
    "basil": {
        "seasonality": {
            "bloom_start_month": 7,
            "bloom_end_month": 9,
            "peak_bloom_months": [8],
            "planting_season": ["spring", "summer"],
            "growth_habit": "Annual",
            "dormancy_months": [11, 12, 1, 2, 3],
            "harvest_season": "summer",
            "best_months_to_plant": [5, 6, 7]
        }
    },
    "mint": {
        "seasonality": {
            "bloom_start_month": 6,
            "bloom_end_month": 9,
            "peak_bloom_months": [7, 8],
            "planting_season": ["spring", "autumn"],
            "growth_habit": "Perennial",
            "dormancy_months": [],
            "harvest_season": "spring",
            "best_months_to_plant": [3, 4, 5, 9, 10]
        }
    },
    "strawberry": {
        "seasonality": {
            "bloom_start_month": 4,
            "bloom_end_month": 6,
            "peak_bloom_months": [5],
            "planting_season": ["summer", "autumn"],
            "growth_habit": "Perennial",
            "dormancy_months": [],
            "harvest_season": "spring",
            "best_months_to_plant": [7, 8, 9]
        }
    },
    "blueberry": {
        "seasonality": {
            "bloom_start_month": 4,
            "bloom_end_month": 5,
            "peak_bloom_months": [5],
            "planting_season": ["autumn", "winter"],
            "growth_habit": "Deciduous shrub",
            "dormancy_months": [12, 1, 2, 3],
            "harvest_season": "summer",
            "best_months_to_plant": [10, 11, 12, 1, 2]
        }
    },
}

# Generic seasonality templates for categories
CATEGORY_DEFAULTS = {
    "flowers": {
        "planting_season": ["spring", "autumn"],
        "dormancy_months": [12, 1, 2],
        "harvest_season": None,
    },
    "vegetables": {
        "planting_season": ["spring", "summer"],
        "dormancy_months": [12, 1, 2],
        "harvest_season": "autumn",
    },
    "herbs": {
        "planting_season": ["spring", "summer"],
        "dormancy_months": [],
        "harvest_season": "summer",
    },
    "fruit": {
        "planting_season": ["autumn", "winter"],
        "dormancy_months": [12, 1, 2],
        "harvest_season": "summer",
    },
    "grasses": {
        "planting_season": ["spring", "autumn"],
        "dormancy_months": [],
        "harvest_season": None,
    },
}

def get_season_for_month(month: int) -> str:
    """Get season name for a given month (1-12)."""
    if month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    elif month in [9, 10, 11]:
        return "autumn"
    else:
        return "winter"

def enrich_plant_seasonality(plant: Dict, plant_id: str) -> Dict:
    """Add seasonality data to a plant record."""
    
    # Check if we have specific seasonality data
    if plant_id in PLANT_SEASONALITY:
        specific = PLANT_SEASONALITY[plant_id]
        if "seasonality" in specific:
            plant["seasonality"] = specific["seasonality"]
            # Also update name/description if available
            if "name" in specific and plant.get("name") != specific["name"]:
                plant["name"] = specific["name"]
            if "scientific_name" in specific and not plant.get("scientific_name"):
                plant["scientific_name"] = specific["scientific_name"]
            if "description" in specific and plant.get("description", "").startswith("ASPCA-listed"):
                plant["description"] = specific["description"]
    else:
        # Use category defaults
        category = plant.get("category", "flowers")
        defaults = CATEGORY_DEFAULTS.get(category, CATEGORY_DEFAULTS["flowers"])
        
        # Try to estimate bloom months based on category
        if category == "vegetables":
            plant["seasonality"] = {
                "bloom_start_month": 5,
                "bloom_end_month": 9,
                "peak_bloom_months": [6, 7, 8],
                "planting_season": defaults["planting_season"],
                "growth_habit": "Annual",
                "dormancy_months": defaults["dormancy_months"],
                "harvest_season": defaults["harvest_season"],
                "best_months_to_plant": [4, 5, 6, 7, 8]
            }
        elif category == "fruit":
            plant["seasonality"] = {
                "bloom_start_month": 3,
                "bloom_end_month": 5,
                "peak_bloom_months": [4],
                "planting_season": defaults["planting_season"],
                "growth_habit": "Perennial shrub",
                "dormancy_months": defaults["dormancy_months"],
                "harvest_season": defaults["harvest_season"],
                "best_months_to_plant": [10, 11, 1, 2, 3]
            }
        elif category == "herbs":
            plant["seasonality"] = {
                "bloom_start_month": 6,
                "bloom_end_month": 9,
                "peak_bloom_months": [7, 8],
                "planting_season": defaults["planting_season"],
                "growth_habit": "Perennial",
                "dormancy_months": defaults["dormancy_months"],
                "harvest_season": defaults["harvest_season"],
                "best_months_to_plant": [4, 5, 6]
            }
        else:
            # Flowers and grasses
            plant["seasonality"] = {
                "bloom_start_month": 5,
                "bloom_end_month": 10,
                "peak_bloom_months": [6, 7, 8, 9],
                "planting_season": defaults["planting_season"],
                "growth_habit": "Perennial" if category == "grasses" else "Annual/Perennial",
                "dormancy_months": defaults["dormancy_months"],
                "harvest_season": defaults["harvest_season"],
                "best_months_to_plant": [3, 4, 5, 9, 10]
            }
    
    return plant

def add_lavender_to_database():
    """Add Lavender to the plant database if not present."""
    with open(DOG_SAFE_PLANTS_PATH, 'r') as f:
        data = json.load(f)
    
    # Check if lavender already exists
    existing_ids = {p["id"] for p in data["plants"]}
    if "lavender" in existing_ids:
        print("[OK] Lavender already in database")
        return False
    
    # Add lavender
    lavender = {
        "id": "lavender",
        "name": "Lavender",
        "scientific_name": "Lavandula angustifolia",
        "category": "flowers",
        "safety_status": "Non-toxic to dogs",
        "image_url": "https://inaturalist-open-data.s3.amazonaws.com/photos/181838/medium.jpg",
        "description": "Fragrant purple flowers on compact evergreen shrubs. Dog-friendly and drought-tolerant. Attracts pollinators.",
        "source_url": "https://www.aspca.org/pet-care/animal-poison-control/dogs-plant-list",
        "image_source_url": "https://www.inaturalist.org/taxa/50559",
        "hardiness_zones_uk": "H4-H7",
        "hardiness_info": {
            "zones_uk": "H4-H7",
            "min_temp_c": -10,
            "max_temp_c": 40
        },
        "growth_habit": "Compact evergreen shrub",
        "sun_exposure": ["Full sun"],
        "soil_preference": "Well-drained, sandy or gravelly soil",
        "care_notes": "Drought-tolerant once established. Prune after flowering. Avoid overwatering."
    }
    
    # Add seasonality
    lavender = enrich_plant_seasonality(lavender, "lavender")
    
    # Insert near start of list (keep it findable)
    data["plants"].insert(1, lavender)
    
    with open(DOG_SAFE_PLANTS_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    
        print("[OK] Added Lavender to database")
    return True

def enrich_all_plants():
    """Add seasonality data to all plants in the database."""
    with open(DOG_SAFE_PLANTS_PATH, 'r') as f:
        data = json.load(f)
    
    plants = data.get("plants", [])
    enriched_count = 0
    
    for plant in plants:
        plant_id = plant.get("id", "").lower()
        plant = enrich_plant_seasonality(plant, plant_id)
        enriched_count += 1
    
    with open(DOG_SAFE_PLANTS_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    
    print(f"[OK] Enriched {enriched_count} plants with seasonality data")

if __name__ == "__main__":
    import sys
    
    if "--add-lavender" in sys.argv:
        add_lavender_to_database()
    
    if "--enrich-all" in sys.argv:
        enrich_all_plants()
    
    if not any(arg in sys.argv for arg in ["--add-lavender", "--enrich-all"]):
        print("Usage:")
        print("  --add-lavender    Add Lavender to database")
        print("  --enrich-all      Add seasonality to all plants")
