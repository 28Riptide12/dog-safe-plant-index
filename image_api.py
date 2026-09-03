"""
Image management API routes for plant database.
Handles image discovery, quality scoring, and batch updates.
"""

import json
import requests
from pathlib import Path
from datetime import datetime
from flask import jsonify, request

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "database"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOG_SAFE_PLANTS_PATH = DATA_DIR / "dog_safe_plants.json"
IMAGE_STATS_PATH = DATA_DIR / "image_stats.json"

def is_placeholder(image_url: str) -> bool:
    """Check if image URL is a placeholder."""
    if not image_url or not image_url.strip():
        return True
    placeholder_patterns = ['noimage', 'imageunavailable', '/image', '/static/placeholders/']
    return any(p in image_url.lower() for p in placeholder_patterns)

def get_plants_needing_images(count: int = 50) -> list:
    """Get plants with placeholder/missing images sorted by priority."""
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    # Filter plants needing images
    needing_images = [
        p for p in data.get("plants", [])
        if is_placeholder(p.get("image_url", ""))
    ]
    
    # Sort by category priority: flowers > vegetables > herbs > fruit > grasses
    priority_order = {"flowers": 0, "vegetables": 1, "herbs": 2, "fruit": 3, "grasses": 4}
    needing_images.sort(key=lambda p: priority_order.get(p.get("category"), 5))
    
    return needing_images[:count]

def get_image_stats() -> dict:
    """Calculate image coverage statistics."""
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    plants = data.get("plants", [])
    total = len(plants)
    with_images = sum(1 for p in plants if not is_placeholder(p.get("image_url", "")))
    
    # Group by category
    by_category = {}
    for plant in plants:
        cat = plant.get("category", "other")
        if cat not in by_category:
            by_category[cat] = {"total": 0, "with_images": 0}
        by_category[cat]["total"] += 1
        if not is_placeholder(plant.get("image_url", "")):
            by_category[cat]["with_images"] += 1
    
    return {
        "timestamp": datetime.now().isoformat(),
        "total_plants": total,
        "plants_with_images": with_images,
        "coverage_percent": round((with_images / total * 100) if total > 0 else 0, 1),
        "plants_needing_images": total - with_images,
        "by_category": by_category
    }

def find_plant_images(plant_id: str, search_both: bool = True) -> dict:
    """
    Find images for a plant from multiple sources.
    Returns candidates with quality scores.
    """
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    plant = next((p for p in data.get("plants", []) if p["id"] == plant_id), None)
    if not plant:
        return {"error": "Plant not found"}
    
    candidates = []
    
    # Import the image sources module
    import sys
    sys.path.insert(0, str(BASE_DIR / "tools"))
    from image_sources import search_wikimedia_commons, search_inaturalist, search_openverse
    
    try:
        # Search Wikimedia Commons
        commons_results = search_wikimedia_commons(
            plant.get("name", ""),
            plant.get("scientific_name", "")
        )
        candidates.extend([
            {
                "url": c.url,
                "source": c.source,
                "title": c.title,
                "quality_score": c.quality_score,
                "resolution": c.resolution,
                "license": c.license,
                "attribution": c.attribution
            }
            for c in commons_results[:5]
        ])

        # Search Openverse
        openverse_results = search_openverse(
            plant.get("name", ""),
            plant.get("scientific_name", "")
        )
        candidates.extend([
            {
                "url": c.url,
                "source": c.source,
                "title": c.title,
                "quality_score": c.quality_score,
                "resolution": c.resolution,
                "license": c.license,
                "attribution": c.attribution
            }
            for c in openverse_results[:5]
        ])
        
        # Search iNaturalist
        if search_both and plant.get("scientific_name"):
            inaturalist_results = search_inaturalist(
                plant.get("scientific_name", ""),
                plant.get("name", "")
            )
            candidates.extend([
                {
                    "url": c.url,
                    "source": c.source,
                    "title": c.title,
                    "quality_score": c.quality_score,
                    "resolution": c.resolution,
                    "license": c.license,
                    "attribution": c.attribution
                }
                for c in inaturalist_results[:5]
            ])
    
    except Exception as e:
        return {"error": str(e)}
    
    # Sort by quality score
    candidates.sort(key=lambda c: c.get("quality_score", 0), reverse=True)
    
    return {
        "plant_id": plant_id,
        "plant_name": plant.get("name"),
        "scientific_name": plant.get("scientific_name"),
        "current_image": plant.get("image_url"),
        "candidates": candidates[:10],
        "timestamp": datetime.now().isoformat()
    }

def approve_image(plant_id: str, image_url: str, source_url: str = "") -> dict:
    """Approve and save an image for a plant."""
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    plant = next((p for p in data.get("plants", []) if p["id"] == plant_id), None)
    if not plant:
        return {"error": "Plant not found", "success": False}
    
    # Update the plant
    plant["image_url"] = image_url
    if source_url:
        plant["image_source_url"] = source_url
    
    # Save
    with open(DOG_SAFE_PLANTS_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    
    return {
        "success": True,
        "plant_id": plant_id,
        "image_url": image_url,
        "timestamp": datetime.now().isoformat()
    }

def batch_approve_images(updates: list) -> dict:
    """Batch approve images for multiple plants."""
    with open(DOG_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    approved_count = 0
    failed_count = 0
    
    for update in updates:
        plant_id = update.get("plant_id")
        image_url = update.get("image_url")
        
        if not plant_id or not image_url:
            failed_count += 1
            continue
        
        plant = next((p for p in data.get("plants", []) if p["id"] == plant_id), None)
        if plant:
            plant["image_url"] = image_url
            if update.get("source_url"):
                plant["image_source_url"] = update.get("source_url")
            approved_count += 1
        else:
            failed_count += 1
    
    # Save all at once
    with open(DOG_SAFE_PLANTS_PATH, 'w') as f:
        json.dump(data, f, indent=2)
    
    return {
        "success": True,
        "approved": approved_count,
        "failed": failed_count,
        "timestamp": datetime.now().isoformat()
    }

# Export for Flask app
def register_image_routes(app):
    """Register image management routes with Flask app."""
    
    @app.get("/admin/image-stats")
    def get_image_statistics():
        """Get image coverage statistics."""
        return jsonify(get_image_stats())
    
    @app.get("/admin/plants-needing-images")
    def plants_needing_images():
        """Get plants that need images, sorted by priority."""
        count = request.args.get("count", 50, type=int)
        plants = get_plants_needing_images(count)
        return jsonify({
            "count": len(plants),
            "plants": plants
        })
    
    @app.get("/admin/find-images/<plant_id>")
    def find_images(plant_id):
        """Find image candidates for a plant."""
        search_both = request.args.get("search_both", "true").lower() == "true"
        result = find_plant_images(plant_id, search_both)
        return jsonify(result)
    
    @app.post("/admin/approve-image")
    def approve_plant_image():
        """Approve an image for a plant."""
        data = request.get_json() or {}
        plant_id = data.get("plant_id")
        image_url = data.get("image_url")
        source_url = data.get("source_url", "")
        
        if not plant_id or not image_url:
            return jsonify({"error": "Missing plant_id or image_url"}), 400
        
        result = approve_image(plant_id, image_url, source_url)
        status = 200 if result.get("success") else 400
        return jsonify(result), status
    
    @app.post("/admin/batch-approve-images")
    def batch_approve_plant_images():
        """Batch approve images for multiple plants."""
        data = request.get_json() or {}
        updates = data.get("updates", [])
        
        if not updates:
            return jsonify({"error": "No updates provided"}), 400
        
        result = batch_approve_images(updates)
        return jsonify(result)
    
    @app.post("/admin/run-image-finder")
    def run_image_finder():
        """Run the image finder tool to discover images."""
        import sys
        import subprocess
        
        max_plants = request.args.get("max_plants", 10, type=int)
        
        try:
            # Run the image finder tool
            result = subprocess.run(
                [sys.executable, "tools/image_sources.py", "--batch", f"--max-plants={max_plants}"],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=300
            )
            
            return jsonify({
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "timestamp": datetime.now().isoformat()
            })
        except Exception as e:
            return jsonify({"error": str(e), "success": False}), 500
