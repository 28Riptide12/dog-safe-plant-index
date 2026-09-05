<#
.SYNOPSIS
  Interactive Plant Photo Manager Helper.

.DESCRIPTION
  Provides an interactive menu to find plants needing photos, search species-specific
  Wikimedia Commons photos via the API, and update photo URLs directly.

.USAGE
  .\manage-photos.ps1
#>

$ErrorActionPreference = 'Stop'
$baseUrl = "http://127.0.0.1:5050"

while ($true) {
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host " PLANT PHOTO MANAGER INTERACTIVE HELPER" -ForegroundColor Cyan
    Write-Host "==================================================" -ForegroundColor Cyan

    Write-Host "Options:" -ForegroundColor Cyan
    Write-Host "  [1] List plants needing photos" -ForegroundColor White
    Write-Host "  [2] Search photo suggestions (multi-source search)" -ForegroundColor White
    Write-Host "  [3] Set/Update a photo URL (custom HTTPS or relative)" -ForegroundColor Green
    Write-Host "  [4] Upload local image file from disk" -ForegroundColor Yellow
    Write-Host "  [5] Open Photo Manager Web Interface (in browser)" -ForegroundColor White
    Write-Host "  [6] Exit" -ForegroundColor White
    Write-Host ""

    $choice = Read-Host "Select option [1-6]"

    switch ($choice.Trim()) {
        "1" {
            try {
                $needing = Invoke-RestMethod -Uri "$baseUrl/api/dog-safe-plants/needing-images?limit=50" -Method Get
                Write-Host ""
                Write-Host "Found $($needing.count) plants needing photos (showing top 50):" -ForegroundColor Yellow
                $needing.plants | Select-Object id, name, scientific_name, safety_status | Format-Table -AutoSize
            } catch {
                Write-Host "Error connecting to local server at $baseUrl. Ensure 'python app.py' is running." -ForegroundColor Red
            }
        }
        "2" {
            $name = Read-Host "Enter plant common name (e.g., Nicotiana or Tobacco Plant)"
            $sci = Read-Host "Enter scientific name or custom keywords (optional)"
            if ([string]::IsNullOrWhiteSpace($name)) { continue }

            try {
                Write-Host "Searching iNaturalist, GBIF, Wikimedia & Openverse for '$name'..." -ForegroundColor Yellow
                $queryStr = "name=$([Uri]::EscapeDataString($name))"
                if (-not [string]::IsNullOrWhiteSpace($sci)) {
                    $queryStr += "&scientific_name=$([Uri]::EscapeDataString($sci))"
                }
                $suggestions = Invoke-RestMethod -Uri "$baseUrl/api/dog-safe-plants/photo-suggestion?$queryStr" -Method Get
                $candidates = $suggestions.candidates
                if (-not $candidates -and $suggestions.image_url) { $candidates = @($suggestions) }

                if ($candidates -and $candidates.Count -gt 0) {
                    Write-Host ""
                    Write-Host "Found $($candidates.Count) suggestions across multi-sources:" -ForegroundColor Green
                    for ($i = 0; $i -lt $candidates.Count; $i++) {
                        $s = $candidates[$i]
                        Write-Host "  [$($i + 1)] Source: $($s.source_name) | Title: $($s.title) | Match: $($s.confidence)" -ForegroundColor White
                        Write-Host "      Image URL: $($s.image_url)" -ForegroundColor DarkGray
                        Write-Host "      Source:    $($s.source_url)" -ForegroundColor DarkGray
                    }
                } else {
                    Write-Host "No suggestions found for '$name'." -ForegroundColor Yellow
                }
            } catch {
                Write-Host "Error fetching suggestions: $_" -ForegroundColor Red
            }
        }
        "3" {
            $plantId = Read-Host "Enter target Plant ID (e.g., rhubarb)"
            if ([string]::IsNullOrWhiteSpace($plantId)) { continue }
            $imageUrl = Read-Host "Enter Image URL (https://... or /static/...)"
            if ([string]::IsNullOrWhiteSpace($imageUrl)) { continue }
            $sourceUrl = Read-Host "Enter Source URL (optional, e.g. Wikimedia page or Custom Source)"

            try {
                $body = @{
                    image_url = $imageUrl
                    image_source_url = $sourceUrl
                    is_custom = $true
                } | ConvertTo-Json

                $res = Invoke-RestMethod -Uri "$baseUrl/api/dog-safe-plants/$plantId/photo" -Method Post -Body $body -ContentType "application/json"
                Write-Host "✓ Photo updated successfully for $plantId!" -ForegroundColor Green
            } catch {
                Write-Host "Error updating photo: $_" -ForegroundColor Red
            }
        }
        "4" {
            $plantId = Read-Host "Enter target Plant ID (e.g. tobacco-plant)"
            if ([string]::IsNullOrWhiteSpace($plantId)) { continue }
            $filePath = Read-Host "Enter absolute path to image file on disk (e.g. C:\photos\plant.jpg)"
            if (-not (Test-Path $filePath)) {
                Write-Host "File not found at '$filePath'." -ForegroundColor Red
                continue
            }
            $sourceAttr = Read-Host "Enter source attribution (optional, e.g. My Garden Photo)"
            if ([string]::IsNullOrWhiteSpace($sourceAttr)) { $sourceAttr = "User Upload" }

            try {
                Write-Host "Uploading $filePath..." -ForegroundColor Yellow
                $curlCmd = "curl.exe -s -F `"file=@$filePath`" -F `"source_url=$sourceAttr`" `"$baseUrl/api/dog-safe-plants/$plantId/upload-photo`""
                $resJson = Invoke-Expression $curlCmd | ConvertFrom-Json
                if ($resJson.image_url) {
                    Write-Host "✓ Image uploaded successfully!" -ForegroundColor Green
                    Write-Host "  Image URL: $($resJson.image_url)" -ForegroundColor White
                } else {
                    Write-Host "Upload failed: $($resJson.error)" -ForegroundColor Red
                }
            } catch {
                Write-Host "Error uploading photo: $_" -ForegroundColor Red
            }
        }
        "5" {
            Write-Host "Opening http://127.0.0.1:5050/plants (Photo Manager UI)..." -ForegroundColor Green
            Start-Process "http://127.0.0.1:5050/plants"
        }
        "6" { break }
        default { Write-Host "Please select 1, 2, 3, 4, 5, or 6." -ForegroundColor Yellow }
    }
}
