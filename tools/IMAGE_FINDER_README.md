# Automatic Plant Image Finder

A Python tool that automatically finds and updates missing plant images from Wikimedia Commons.

## Features

- ✅ Scans plant database for missing/placeholder images
- ✅ Searches Wikimedia Commons for better quality images
- ✅ Intelligent scientific name matching
- ✅ Rate-limit protection with exponential backoff
- ✅ Backup database before updates
- ✅ Dry-run mode for previewing changes

## Usage

### Basic Usage

```bash
cd "C:\Web app"
.venv\Scripts\python.exe tools/find_missing_images.py
```

### Find 10 Missing Images

```bash
.venv\Scripts\python.exe tools/find_missing_images.py --max-plants 10
```

### Dry Run (Preview Only)

```bash
.venv\Scripts\python.exe tools/find_missing_images.py --max-plants 5 --dry-run
```

### Custom Delay Between Requests

```bash
.venv\Scripts\python.exe tools/find_missing_images.py --max-plants 10 --delay 5.0
```

## Command Line Options

- `--max-plants N` - Maximum number of plants to update (default: 20)
- `--dry-run` - Show what would be updated without saving
- `--delay S` - Delay between Commons API requests in seconds (default: 1.0)

## How It Works

### Priority Order

Plants are processed in this priority order:
1. **Flowers** - Most common category
2. **Vegetables** - Food-related plants
3. **Herbs** - Culinary/medicinal
4. **Fruit** - Edible plants
5. **Grasses** - Ornamental plants

Within each category, plants are sorted alphabetically.

### Image Matching

The tool searches Wikimedia Commons using the plant's scientific name for maximum accuracy. It filters results to only include images that match all significant tokens from the scientific name.

### Rate Limiting

Commons API has strict rate limits. The tool includes:
- Automatic detection of 429 (Too Many Requests) errors
- Exponential backoff (2s, 4s, 8s...)
- Configurable delay between requests
- Graceful handling of rate-limited requests

**Recommended settings:**
- For testing: `--max-plants 3 --delay 8.0`
- For production: `--max-plants 15 --delay 5.0`

## Examples

### Schedule on Windows Task Scheduler

Create a batch file `run_image_finder.bat`:

```batch
@echo off
cd "C:\Web app"
.venv\Scripts\python.exe tools/find_missing_images.py --max-plants 10 --delay 5.0
```

Then create a scheduled task:
1. Open Task Scheduler
2. Create Basic Task
3. Set trigger (e.g., Daily at 2 AM)
4. Set action to run the batch file

### Manual Weekly Update

Run this command weekly to find and update 15 more images:

```bash
.venv\Scripts\python.exe tools/find_missing_images.py --max-plants 15 --delay 5.0
```

## Statistics

### Current Status

- Total plants: 608
- Plants with images: ~575
- Plants needing images: ~33
- Successfully updated: 1 (Aluminum Plant)

### Placeholder Patterns Detected

The tool recognizes these as placeholders:
- Empty or blank URLs
- ASPCA/source placeholder images
- Generic category placeholders (e.g., `/static/placeholders/flowers.svg`)
- "noimage" or "imageunavailable" patterns

## Troubleshooting

### "429 Client Error: Too Many Requests"

The Commons API is rate-limiting. Solutions:
- Increase `--delay` (try 8.0 or higher)
- Run during off-peak hours
- Use `--max-plants` to limit batch size
- Wait a few minutes before retrying

### "No Commons match found"

Some plants don't have photos on Commons, or the scientific name doesn't match well. The tool will skip these and continue with others.

### Database Backup

Before each update run, a backup is created in the `backups/` folder. If something goes wrong, you can restore from the latest backup file there.

## Future Improvements

- [ ] Add support for other image sources (iNaturalist, Flickr)
- [ ] Implement caching of search results
- [ ] Add manual image curation interface
- [ ] Support for batch imports from CSV
- [ ] Image quality scoring system
- [ ] Automatic retry with different search terms

## Files Modified

- `dog_safe_plants.json` - Plant database (updated with new image URLs)
- `backups/*.json` - Timestamped backups before updates
