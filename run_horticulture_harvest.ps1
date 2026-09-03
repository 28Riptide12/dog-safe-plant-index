Set-Location 'C:\Web app'
# Running with no arguments shows an interactive menu: pick a data source
# (RHS horticulture facts, Wikipedia descriptions, or Pet Poison Helpline
# review-queue candidates), then batch size, worker count (concurrency =
# speed), and delay. Already-harvested plants are skipped automatically per
# source, so you can run this in short batches any time.
& '.\.venv\Scripts\python.exe' harvest_plant_horticulture.py
Write-Host ""
Write-Host "Harvest finished (or stopped). Progress up to this point is saved."
Write-Host "Run this script again any time to continue with the remaining plants."
Write-Host "Press Enter to close this window."
Read-Host
