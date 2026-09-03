# Dog Safe Plant Index

Standalone export of the dog-safe plant catalogue, review queue, image tooling, and planner.

## What it includes

- Flask app for `/plants`, `/api/dog-safe-plants*`, `/api/plant-review-queue*`, `/api/climate/*`, `/api/health/paths`, `/api/plant-lifecycle-hardiness`, `/api/plant-toxicity-evidence`, `/api/plant-synonyms`, `/api/plant-colour-profiles`, `/api/plants-by-climate`, `/api/plant-image`, `/api/plant-local-image`, `/api/plant-favorites*`, `/api/user-plants*`, `/api/care-tasks*`, `/admin/images`, `/ai-garden-planner`, `/api/generate-garden-plan`, and `/docs`
- JSON plant datasets plus SQLite-backed user/favorites/task storage
- plant harvesting, scraping, synonym, and image-management scripts

## Setup

```powershell
pip install -r requirements.txt
flask --app app run --debug
```

Open `http://127.0.0.1:5000/plants`.

## Important paths

- `database/dog_safe_plants.json` – live catalogue
- `database/plant_review_queue.json` – staged review candidates
- `database/plant_library.json` – shared favorite/care metadata seed
- `plant_user_data.db` – runtime SQLite user data (gitignored)
- `plant_image_cache/` – optional local image cache (gitignored)

## Common scripts

```powershell
python scrape_dog_safe_plants.py
python harvest_plant_horticulture.py
python harvest_plant_synonyms.py
python tools/harvest_plant_profiles.py --limit 80
```
