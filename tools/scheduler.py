#!/usr/bin/env python3
"""
Automated image finder scheduler for Windows Task Scheduler.
Runs on a daily schedule to discover and cache images from Wikimedia Commons and iNaturalist.
"""

import json
import logging
from pathlib import Path
from datetime import datetime
import sys
import subprocess

BASE_DIR = Path(__file__).resolve().parent.parent
DOGS_SAFE_PLANTS_PATH = BASE_DIR / "database" / "dog_safe_plants.json"
IMAGE_CACHE_PATH = BASE_DIR / "database" / "image_cache.json"
SCHEDULER_LOG_PATH = BASE_DIR / "logs" / "image_scheduler.log"

# Setup logging
SCHEDULER_LOG_PATH.parent.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(SCHEDULER_LOG_PATH),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def is_placeholder(image_url: str) -> bool:
    """Check if image URL is a placeholder."""
    if not image_url or not image_url.strip():
        return True
    patterns = ['noimage', 'imageunavailable', '/image', '/static/placeholders/']
    return any(p in image_url.lower() for p in patterns)

def get_plants_to_process(limit: int = 10) -> list:
    """Get plants needing images, sorted by priority."""
    with open(DOGS_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    needing = [
        p for p in data.get("plants", [])
        if is_placeholder(p.get("image_url", ""))
    ]
    
    # Sort by category priority
    priority = {"flowers": 0, "vegetables": 1, "herbs": 2, "fruit": 3, "grasses": 4}
    needing.sort(key=lambda p: priority.get(p.get("category"), 5))
    
    return needing[:limit]

def run_image_finder(max_plants: int = 10) -> dict:
    """Run the image finder tool."""
    logger.info(f"Starting image finder for {max_plants} plants...")
    
    try:
        result = subprocess.run(
            [sys.executable, "tools/image_sources.py", "--batch", f"--max-plants={max_plants}"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=600  # 10 minutes max
        )
        
        success = result.returncode == 0
        
        if success:
            logger.info(f"Image finder completed successfully")
        else:
            logger.error(f"Image finder failed: {result.stderr}")
        
        # Save run statistics
        stats = {
            "timestamp": datetime.now().isoformat(),
            "success": success,
            "plants_processed": max_plants,
            "stdout_lines": len(result.stdout.split('\n')),
            "return_code": result.returncode
        }
        
        return stats
    
    except subprocess.TimeoutExpired:
        logger.error("Image finder timed out (10 minutes)")
        return {"timestamp": datetime.now().isoformat(), "success": False, "error": "Timeout"}
    except Exception as e:
        logger.error(f"Error running image finder: {e}")
        return {"timestamp": datetime.now().isoformat(), "success": False, "error": str(e)}

def load_or_create_cache() -> dict:
    """Load existing cache or create new one."""
    if IMAGE_CACHE_PATH.exists():
        with open(IMAGE_CACHE_PATH) as f:
            return json.load(f)
    return {"runs": [], "last_successful": None}

def save_cache(cache: dict):
    """Save cache to disk."""
    with open(IMAGE_CACHE_PATH, 'w') as f:
        json.dump(cache, f, indent=2)

def main():
    """Main scheduler task."""
    logger.info("=" * 60)
    logger.info("Plant Image Finder - Scheduled Run")
    logger.info("=" * 60)
    
    # Load or create cache
    cache = load_or_create_cache()
    
    # Get plants needing images
    plants = get_plants_to_process(limit=10)
    logger.info(f"Found {len(plants)} plants needing images")
    
    if not plants:
        logger.info("No plants need images - all covered!")
        return
    
    # Run finder
    stats = run_image_finder(max_plants=len(plants))
    
    # Update cache
    cache["runs"].append(stats)
    if stats.get("success"):
        cache["last_successful"] = datetime.now().isoformat()
    
    # Keep only last 30 runs
    cache["runs"] = cache["runs"][-30:]
    
    save_cache(cache)
    
    # Summary
    with open(DOGS_SAFE_PLANTS_PATH) as f:
        data = json.load(f)
    
    total = len(data.get("plants", []))
    with_images = sum(1 for p in data.get("plants", []) if not is_placeholder(p.get("image_url", "")))
    coverage = round(with_images / total * 100) if total > 0 else 0
    
    logger.info(f"Current coverage: {with_images}/{total} ({coverage}%)")
    logger.info("Scheduled run completed")
    
    return 0 if stats.get("success") else 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
