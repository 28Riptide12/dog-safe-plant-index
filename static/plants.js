const grid = document.querySelector('#plant-grid');
const status = document.querySelector('#plants-status');
let plants = [];
let category = 'all';
let plantView = 'catalogue';
const filters = { search: '', safety: 'all', season: 'all', lifecycle: 'all', light: 'all', flowerColour: [], foliageColour: [], colourPattern: [], height: 'all', spread: 'all', tenderness: 'all', container: 'all', watering: 'all', pollinator: 'all', fragrance: 'all', habit: 'all', habitats: ['indoor', 'outdoor'], favorites: false, hideTrees: true, showToxic: false, reviewOnly: false, climateZone: null };
let selectedPostcode = localStorage.getItem('selectedPostcode') || '';
let selectedClimateZone = localStorage.getItem('selectedClimateZone') || '';
const favoriteIds = new Set();
const care = {};
const imageBrokenIds = new Set();
let librarySyncTimer;
let pickerCategory = 'all';
let addPlantModalDirty = false;
let saveAndAddAnother = false;

// Pagination
let currentPage = 1;
const itemsPerPage = 12;
let totalPages = 1;
let previousVisibleCount = 0; // Track for detecting filter changes
let lastVisiblePlants = [];
let lastPagePlants = [];
let plantDisplayMode = localStorage.getItem('plantDisplayMode') || 'cards';
let profileOverrides = {};
let lifecycleHardinessOverrides = {};
let toxicityEvidenceOverrides = {};
let plantSynonymOverrides = {};
let plantColourOverrides = {};
let plantReviewQueue = [];
let spellcheckDictionary = { common_misspellings: {} };

function applyPlantDarkMode(enabled) {
  document.body.classList.toggle('dark-mode', enabled);
  const darkToggle = document.querySelector('#plant-dark-toggle');
  if (darkToggle) {
    darkToggle.checked = enabled;
    darkToggle.setAttribute('aria-checked', String(enabled));
  }
  localStorage.setItem('plantDarkMode', enabled ? '1' : '0');
}

function isDialogDark() {
  return document.body.classList.contains('dark-mode') || document.body.classList.contains('dark');
}

function showDialog({ title = 'Notice', message = '', confirmText = 'OK', cancelText = 'Cancel', showCancel = false, showInput = false, defaultValue = '', danger = false }) {
  return new Promise(resolve => {
    const dark = isDialogDark();
    const overlay = document.createElement('div');
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(15,23,42,0.55);display:flex;align-items:center;justify-content:center;z-index:9999;padding:16px;';
    const panel = document.createElement('div');
    panel.style.cssText = `width:min(560px,100%);background:${dark ? '#111827' : '#ffffff'};color:${dark ? '#e5e7eb' : '#111827'};border:1px solid ${dark ? '#374151' : '#e7e5e4'};border-radius:12px;box-shadow:0 20px 40px rgba(0,0,0,0.25);padding:18px;`;
    panel.innerHTML = `
      <h3 style="margin:0 0 8px 0;font-size:1.05rem;font-weight:800;">${escapeHtml(title)}</h3>
      <p style="margin:0 0 14px 0;white-space:pre-wrap;line-height:1.5;">${escapeHtml(message)}</p>
      ${showInput ? `<input id="dialog-input" type="text" value="${escapeHtml(defaultValue)}" style="width:100%;padding:10px;border-radius:8px;border:1px solid ${dark ? '#4b5563' : '#d6d3d1'};background:${dark ? '#1f2937' : '#fff'};color:inherit;margin-bottom:14px;">` : ''}
      <div style="display:flex;justify-content:flex-end;gap:8px;">
        ${showCancel ? `<button id="dialog-cancel" type="button" style="padding:8px 12px;border-radius:8px;border:1px solid ${dark ? '#4b5563' : '#d6d3d1'};background:transparent;color:inherit;font-weight:700;">${escapeHtml(cancelText)}</button>` : ''}
        <button id="dialog-confirm" type="button" style="padding:8px 12px;border-radius:8px;border:1px solid ${danger ? '#b91c1c' : '#047857'};background:${danger ? '#b91c1c' : '#047857'};color:#fff;font-weight:700;">${escapeHtml(confirmText)}</button>
      </div>
    `;
    overlay.appendChild(panel);
    document.body.appendChild(overlay);
    const input = panel.querySelector('#dialog-input');
    if (input) input.focus();
    let settled = false;
    const cleanup = result => {
      if (settled) return;
      settled = true;
      overlay.remove();
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const onKey = event => {
      if (event.key === 'Escape' && showCancel) cleanup({ ok: false, value: null });
      if (event.key === 'Enter') cleanup({ ok: true, value: input ? input.value : null });
    };
    document.addEventListener('keydown', onKey);
    overlay.addEventListener('click', event => { if (event.target === overlay && showCancel) cleanup({ ok: false, value: null }); });
    panel.querySelector('#dialog-confirm')?.addEventListener('click', () => cleanup({ ok: true, value: input ? input.value : null }));
    panel.querySelector('#dialog-cancel')?.addEventListener('click', () => cleanup({ ok: false, value: null }));
  });
}

async function askConfirm(message, danger = false) {
  const result = await showDialog({ title: 'Please confirm', message, showCancel: true, confirmText: danger ? 'Delete' : 'Confirm', cancelText: 'Cancel', danger });
  return result.ok;
}

async function askPrompt(message, defaultValue = '', title = 'Input') {
  const result = await showDialog({ title, message, showInput: true, defaultValue, showCancel: true, confirmText: 'Save', cancelText: 'Cancel' });
  return result.ok ? result.value : null;
}

async function showAlert(message, title = 'Notice') {
  await showDialog({ title, message, showCancel: false, confirmText: 'OK' });
}

async function syncLibrary() {
  clearTimeout(librarySyncTimer);
  librarySyncTimer = setTimeout(async () => {
    try { await fetch('/api/dog-safe-plants/library', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ favorite_ids: [...favoriteIds], care }) }); }
    catch (_) { document.querySelector('#favorites-status')?.replaceChildren(document.createTextNode('Could not save shared library changes.')); }
  }, 150);
}

async function loadLibrary() {
  try {
    const response = await fetch('/api/dog-safe-plants/library');
    const data = await response.json();
    (data.favorite_ids || []).forEach(id => favoriteIds.add(id));
    Object.assign(care, data.care || {});
    const favoritesResponse = await fetch(`/api/plant-favorites?user_id=${encodeURIComponent(userId)}`);
    if (favoritesResponse.ok) (await favoritesResponse.json()).favorites.forEach(item => favoriteIds.add(item.plant_id));
  }
  catch (_) { document.querySelector('#favorites-status')?.replaceChildren(document.createTextNode('Shared library is unavailable.')); }
}

async function loadProfileOverrides() {
  try {
    const response = await fetch('/static/plant_profile_overrides.json');
    if (!response.ok) return;
    const data = await response.json();
    profileOverrides = data && typeof data === 'object' ? (data.plants || {}) : {};
  } catch (_) {
    profileOverrides = {};
  }
}

async function loadLifecycleHardinessOverrides() {
  try {
    const response = await fetch('/api/plant-lifecycle-hardiness');
    if (!response.ok) return;
    const data = await response.json();
    lifecycleHardinessOverrides = data && typeof data === 'object' ? (data.plants || {}) : {};
  } catch (_) {
    lifecycleHardinessOverrides = {};
  }
}

async function loadToxicityEvidenceOverrides() {
  try {
    const response = await fetch('/api/plant-toxicity-evidence');
    if (!response.ok) return;
    const data = await response.json();
    toxicityEvidenceOverrides = data && typeof data === 'object' ? (data.plants || {}) : {};
  } catch (_) {
    toxicityEvidenceOverrides = {};
  }
}

async function loadPlantSynonymOverrides() {
  try {
    const response = await fetch('/api/plant-synonyms');
    if (!response.ok) return;
    const data = await response.json();
    plantSynonymOverrides = data && typeof data === 'object' ? (data.plants || {}) : {};
  } catch (_) {
    plantSynonymOverrides = {};
  }
}

async function loadPlantColourOverrides() {
  try {
    const response = await fetch('/api/plant-colour-profiles');
    if (!response.ok) return;
    const data = await response.json();
    plantColourOverrides = data && typeof data === 'object' ? (data.plants || {}) : {};
  } catch (_) {
    plantColourOverrides = {};
  }
}

async function loadPlantReviewQueue() {
  try {
    const response = await fetch('/api/plant-review-queue');
    if (!response.ok) return;
    const data = await response.json();
    plantReviewQueue = data && typeof data === 'object' ? (data.plants || []) : [];
  } catch (_) {
    plantReviewQueue = [];
  }
}

function normaliseSafetyStatus(value) {
  const text = String(value || '').trim();
  const lowered = text.toLowerCase();
  if (!lowered) return 'Unknown';
  if (lowered.includes('may be toxic') || lowered.includes('may-be-toxic') || lowered.includes('possible toxic')) return 'May be Toxic';
  if (lowered.includes('non-toxic') || lowered.includes('nontoxic') || lowered.includes('dog safe') || lowered.includes('safe')) return 'Non-toxic';
  if (lowered.includes('toxic')) return 'Toxic';
  return text;
}

function isRiskySafetyStatus(value) {
  const safety = normaliseSafetyStatus(value);
  return safety === 'Toxic' || safety === 'May be Toxic';
}

async function handleReviewQueueAction(plantId, action) {
  const response = await fetch(`/api/plant-review-queue/${encodeURIComponent(plantId)}/${action}`, { method: 'POST' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.error || `Review action failed (${action}).`);
  }
  await loadPlantReviewQueue();
  try {
    const liveResponse = await fetch('/api/dog-safe-plants');
    if (liveResponse.ok) {
      const liveData = await liveResponse.json();
      plants = Array.isArray(liveData.plants) ? liveData.plants : [];
    }
  } catch (_) { }
  return data;
}

/**
 * Climate zone functions
 */
async function lookupClimateZone(postcode) {
  try {
    const response = await fetch(`/api/climate/postcode/${encodeURIComponent(postcode)}`);
    const data = await response.json();
    if (!response.ok) {
      document.querySelector('#climate-status').textContent = `Error: ${data.error}`;
      return null;
    }
    selectedPostcode = postcode;
    selectedClimateZone = data.hardiness_zone;
    filters.climateZone = data.hardiness_zone;
    localStorage.setItem('selectedPostcode', postcode);
    localStorage.setItem('selectedClimateZone', data.hardiness_zone);
    
    const zoneInfo = data.zone_info || {};
    document.querySelector('#climate-zone-display').innerHTML = `
      <div class="rounded bg-white p-2">
        <p class="font-semibold text-stone-900">${data.hardiness_zone}</p>
        <p class="text-xs text-stone-600">${zoneInfo.label || ''}</p>
      </div>
    `;
    document.querySelector('#climate-status').textContent = `Showing plants suitable for ${data.hardiness_zone}`;
    renderPlants();
    return data.hardiness_zone;
  } catch (error) {
    document.querySelector('#climate-status').textContent = `Error: ${error.message}`;
    return null;
  }
}

function clearClimateZone() {
  selectedPostcode = '';
  selectedClimateZone = '';
  filters.climateZone = null;
  localStorage.removeItem('selectedPostcode');
  localStorage.removeItem('selectedClimateZone');
  document.querySelector('#climate-postcode-input').value = '';
  document.querySelector('#climate-zone-display').innerHTML = '';
  document.querySelector('#climate-status').textContent = '';
  renderPlants();
}

// Get or create user ID for server-side storage
let userId = localStorage.getItem('plantUserId');
if (!userId) {
  userId = 'user_' + Date.now();
  localStorage.setItem('plantUserId', userId);
}

let userPlants = [];
let careTasks = [];

/**
 * API functions for server-side plant management
 */
async function addFavorite(plantId) {
  try {
    const response = await fetch('/api/plant-favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, plant_id: plantId })
    });
    return response.ok;
  } catch (_) { return false; }
}

async function removeFavorite(plantId) {
  try {
    const response = await fetch(`/api/plant-favorites/${plantId}?user_id=${userId}`, { method: 'DELETE' });
    return response.ok;
  } catch (_) { return false; }
}

async function addUserPlant(plantId, plantName, locationName = '', notes = '') {
  try {
    const response = await fetch('/api/user-plants', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, plant_id: plantId, plant_name: plantName, location_name: locationName, plant_notes: notes })
    });
    if (response.ok) return await response.json();
    return null;
  } catch (_) { return null; }
}

async function updateUserPlant(plantId, updates) {
  try {
    const response = await fetch(`/api/user-plants/${plantId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId, ...updates })
    });
    if (response.ok) return await response.json();
    return null;
  } catch (_) { return null; }
}

async function deleteUserPlant(plantId) {
  try {
    const response = await fetch(`/api/user-plants/${plantId}?user_id=${userId}`, { method: 'DELETE' });
    return response.ok;
  } catch (_) { return false; }
}

async function loadUserPlants() {
  try {
    const response = await fetch(`/api/user-plants?user_id=${userId}`);
    const data = await response.json();
    userPlants = data.plants || [];
    return userPlants;
  } catch (_) { return []; }
}

async function loadCareTasks() {
  try {
    const response = await fetch(`/api/care-tasks?user_id=${userId}`);
    const data = await response.json();
    careTasks = data.tasks || [];
    return careTasks;
  } catch (_) { return []; }
}

async function createCareTask(userPlantId, taskType = 'watering', frequencyDays = 7) {
  try {
    const response = await fetch('/api/care-tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_plant_id: userPlantId, task_type: taskType, frequency_days: frequencyDays })
    });
    if (response.ok) return await response.json();
    return null;
  } catch (_) { return null; }
}

async function completeTask(taskId) {
  try {
    const response = await fetch(`/api/care-tasks/${taskId}/complete`, { method: 'PUT' });
    if (response.ok) {
      await loadCareTasks();
      return await response.json();
    }
    return null;
  } catch (_) { return null; }
}
const growingGuidance = {
  flowers: {
    typicalGrowingTime: '8-16 weeks',
    sunExposure: 'Sun to partial shade',
    gardenNote: 'Deadhead spent blooms',
    watering: 'Water when the surface is dry',
    soil: 'Fertile, well-drained soil',
    matureSize: '15 cm-2 m',
  },
  fruit: {
    typicalGrowingTime: 'One season to several years',
    sunExposure: 'Sun and regular watering',
    gardenNote: 'Protect developing fruit',
    watering: 'Keep evenly moist while fruiting',
    soil: 'Rich, well-drained soil',
    matureSize: '15 cm-3 m',
  },
  vegetables: {
    typicalGrowingTime: '6-16 weeks',
    sunExposure: 'Full sun preferred',
    gardenNote: 'Harvest regularly',
    watering: 'Water consistently',
    soil: 'Moisture-retentive fertile soil',
    matureSize: '10 cm-1 m',
  },
  herbs: {
    typicalGrowingTime: '6-12 weeks',
    sunExposure: 'Sun and well-drained soil',
    gardenNote: 'Trim regularly for fresh growth',
    watering: 'Allow the surface to dry between watering',
    soil: 'Light, well-drained soil',
    matureSize: '20 cm-1 m',
  },
  grasses: {
    typicalGrowingTime: 'One season to establish',
    sunExposure: 'Usually sun to partial shade',
    gardenNote: 'Cut back or divide as needed',
    watering: 'Water during establishment, then as needed',
    soil: 'Well-drained soil suited to the variety',
    matureSize: '30 cm-2.5 m',
  },
};

function setupPlantImport() {
  const toggle = document.querySelector('#plant-settings-toggle');
  const modal = document.querySelector('#plant-settings');
  const input = document.querySelector('#plant-import-file');
  const button = document.querySelector('#plant-import-button');
  const preview = document.querySelector('#plant-import-preview');
  const importStatus = document.querySelector('#plant-import-status');
  const bulkButton = document.querySelector('#bulk-find-photos');
  const mergeButton = document.querySelector('#merge-scraped-plants');
  if (!toggle || !modal || !input || !button) return;
  toggle.addEventListener('click', () => { modal.classList.remove('hidden'); });
  modal.addEventListener('click', (e) => { if (e.target === modal) modal.classList.add('hidden'); });
  input.addEventListener('change', async () => {
    const file = input.files[0]; button.disabled = !file; importStatus.classList.add('hidden');
    if (!file) { preview.textContent = 'Choose a JSON file to preview it.'; return; }
    try { const data = JSON.parse(await file.text()); const rows = Array.isArray(data) ? data : data.plants; if (!Array.isArray(rows)) throw new Error('JSON must contain a plants array.'); preview.textContent = `Ready to verify ${rows.length} plant record${rows.length === 1 ? '' : 's'} from ${file.name}.`; }
    catch (error) { preview.textContent = `File check failed: ${error.message}`; button.disabled = true; }
  });
  button.addEventListener('click', async () => {
    const file = input.files[0]; if (!file) return; button.disabled = true; button.textContent = 'Verifying...';
    try { const form = new FormData(); form.append('file', file); const response = await fetch('/api/dog-safe-plants/import', { method: 'POST', body: form }); const data = await response.json(); if (!response.ok) throw new Error(data.error); plants = (await fetch('/api/dog-safe-plants').then(result => result.json())).plants; renderPlants(); importStatus.textContent = `${data.imported} plant${data.imported === 1 ? '' : 's'} imported safely.${data.skipped?.length ? ` Skipped: ${data.skipped.join(', ')}.` : ''}`; importStatus.className = 'mt-3 rounded-lg bg-emerald-100 p-3 text-sm text-emerald-800'; }
    catch (error) { importStatus.textContent = error.message; importStatus.className = 'mt-3 rounded-lg bg-red-100 p-3 text-sm text-red-800'; }
    finally { importStatus.classList.remove('hidden'); button.disabled = false; button.textContent = 'Verify and import'; }
  });
  bulkButton?.addEventListener('click', async () => {
    if (!plants.length) return;
    const targets = plants.filter(plant => imageBrokenIds.has(plant.id));
    if (!targets.length) { importStatus.classList.remove('hidden'); importStatus.className = 'mt-3 rounded-lg bg-emerald-100 p-3 text-sm text-emerald-800'; importStatus.textContent = 'No missing images detected. Every loaded plant image is available.'; return; }
    bulkButton.disabled = true; bulkButton.textContent = 'Searching...'; importStatus.classList.remove('hidden'); importStatus.className = 'mt-3 rounded-lg bg-stone-100 p-3 text-sm text-stone-700'; importStatus.textContent = `Searching Commons for ${targets.length} missing plant photo${targets.length === 1 ? '' : 's'}...`;
    const suggestions = [];
    for (const plant of targets) {
      try {
        const response = await fetch(`/api/dog-safe-plants/photo-suggestion?name=${encodeURIComponent(plant.name)}&scientific_name=${encodeURIComponent(plant.scientific_name)}`);
        if (response.ok) suggestions.push({ plant, suggestion: await response.json() });
      } catch (_) { }
    }
    if (!suggestions.length) { importStatus.textContent = 'No confident photo matches were found. No plants were changed.'; bulkButton.disabled = false; bulkButton.textContent = 'Find missing photos in bulk'; return; }
    const approved = await askConfirm(`Found ${suggestions.length} confident species-specific photo matches. Approve and save all of them?\n\nEach match was searched using the scientific name and will be backed up before saving.`);
    if (!approved) { importStatus.textContent = `Found ${suggestions.length} matches. No plants were changed.`; bulkButton.disabled = false; bulkButton.textContent = 'Find missing photos in bulk'; return; }
    let saved = 0;
    for (const { plant, suggestion } of suggestions) {
      try {
        const response = await fetch(`/api/dog-safe-plants/${encodeURIComponent(plant.id)}/photo`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ image_url: suggestion.image_url, image_source_url: suggestion.source_url }) });
        if (response.ok) { plant.image_url = suggestion.image_url; imageBrokenIds.delete(plant.id); saved += 1; }
      } catch (_) { }
    }
    renderPlants(); importStatus.className = 'mt-3 rounded-lg bg-emerald-100 p-3 text-sm text-emerald-800'; importStatus.textContent = `${saved} of ${suggestions.length} approved photo${suggestions.length === 1 ? '' : 's'} saved with backups.`; bulkButton.disabled = false; bulkButton.textContent = 'Find missing photos in bulk';
  });
  mergeButton?.addEventListener('click', async () => {
    mergeButton.disabled = true; mergeButton.textContent = 'Checking...'; importStatus.classList.remove('hidden'); importStatus.className = 'mt-3 rounded-lg bg-stone-100 p-3 text-sm text-stone-700';
    try {
      const previewResponse = await fetch('/api/dog-safe-plants/merge-preview'); const previewData = await previewResponse.json(); if (!previewResponse.ok) throw new Error(previewData.error);
      const sample = previewData.sample_new.length ? `\n\nExamples: ${previewData.sample_new.join(', ')}` : '';
      const approved = await askConfirm(`Scraped catalogue: ${previewData.scraped} records.\nNew records: ${previewData.new}.\nDuplicates to skip: ${previewData.duplicates}.${sample}\n\nMerge new validated ASPCA records into the live catalogue? A backup will be created.`);
      if (!approved) { importStatus.textContent = 'Merge cancelled. No plants were changed.'; return; }
      const response = await fetch('/api/dog-safe-plants/merge-scraped', { method: 'POST' }); const data = await response.json(); if (!response.ok) throw new Error(data.error);
      plants = (await fetch('/api/dog-safe-plants').then(result => result.json())).plants; renderPlants(); importStatus.className = 'mt-3 rounded-lg bg-emerald-100 p-3 text-sm text-emerald-800'; importStatus.textContent = `${data.imported} new plants merged safely. ${data.duplicates} duplicates skipped. Backup created.`;
    } catch (error) { importStatus.className = 'mt-3 rounded-lg bg-red-100 p-3 text-sm text-red-800'; importStatus.textContent = error.message; }
    finally { importStatus.classList.remove('hidden'); mergeButton.disabled = false; mergeButton.textContent = 'Merge scraped catalogue'; }
  });
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));
}

function candidateDisplayTitle(candidate, index, plant) {
  const raw = String(candidate?.title || '').trim();
  const fallbackBase = String(plant?.scientific_name || plant?.name || 'Plant photo').trim();
  if (!raw) return `${fallbackBase} candidate ${index + 1}`;

  let cleaned = raw.replace(/^File:/i, '');
  cleaned = cleaned.replace(/\.(jpe?g|png|webp|gif|tiff?)$/i, '');
  cleaned = cleaned.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim();

  const noisy = /(need to id|herbarium|\b\d{4}-\d{2}-\d{2}\b|\b\d{8,}\b)/i.test(cleaned) || cleaned.length > 95;
  if (noisy) {
    const source = String(candidate?.source_name || '').trim();
    const sourceLabel = source ? ` (${source})` : '';
    return `${fallbackBase} candidate ${index + 1}${sourceLabel}`;
  }

  return cleaned.length > 95 ? `${cleaned.slice(0, 92)}...` : cleaned;
}

function choosePhotoCandidate(plant, candidates) {
  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'plant-modal';
    overlay.innerHTML = `
      <div class="plant-modal-card photo-choice-modal-card" role="dialog" aria-modal="true" aria-label="Choose a photo for ${escapeHtml(plant.name)}">
        <button type="button" class="plant-modal-close" aria-label="Close">×</button>
        <p class="plant-eyebrow text-emerald-700">Choose a photo</p>
        <h3 class="mt-1 text-2xl font-bold">Best match for ${escapeHtml(plant.name)}</h3>
        <p class="mt-2 text-sm text-stone-600">Select a preview image and confirm.</p>
        <div class="photo-choice-grid"></div>
        <div class="mt-4 flex items-center justify-end gap-2">
          <button type="button" class="button-secondary" data-picker-cancel>Cancel</button>
          <button type="button" class="button-secondary" data-picker-confirm disabled>Confirm selected photo</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    const grid = overlay.querySelector('.photo-choice-grid');
    const confirmButton = overlay.querySelector('[data-picker-confirm]');
    const closeButton = overlay.querySelector('.plant-modal-close');
    const cancelButton = overlay.querySelector('[data-picker-cancel]');
    let selected = null;
    let settled = false;

    const cleanup = value => {
      if (settled) return;
      settled = true;
      document.removeEventListener('keydown', onKeyDown);
      overlay.remove();
      resolve(value);
    };

    const onKeyDown = event => {
      if (event.key === 'Escape') cleanup(null);
    };
    document.addEventListener('keydown', onKeyDown);

    closeButton?.addEventListener('click', () => cleanup(null));
    cancelButton?.addEventListener('click', () => cleanup(null));
    overlay.addEventListener('click', event => {
      if (event.target === overlay) cleanup(null);
    });
    confirmButton?.addEventListener('click', () => cleanup(selected));

    candidates.forEach((candidate, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'photo-choice-item';
      button.innerHTML = `
        <img src="${escapeHtml(candidate.image_url || '')}" alt="${escapeHtml(candidateDisplayTitle(candidate, index, plant))}" loading="lazy">
        <div class="photo-choice-title">${escapeHtml(candidateDisplayTitle(candidate, index, plant))}</div>
        <div class="photo-choice-meta">${escapeHtml(String(candidate.confidence || 'low').toUpperCase())} · ${escapeHtml(candidate.source_name || 'Source')}</div>
      `;
      button.addEventListener('click', () => {
        grid.querySelectorAll('.photo-choice-item').forEach(item => item.classList.remove('is-selected'));
        button.classList.add('is-selected');
        selected = candidate;
        if (confirmButton) confirmButton.disabled = false;
      });
      grid.appendChild(button);
    });
  });
}

function imageSources(plant) {
  const sources = [];
  if (plant.local_image_file) sources.push(`/api/plant-local-image?file=${encodeURIComponent(plant.local_image_file)}`);
  const imageUrl = (plant.image_url || '').trim();
  if (!imageUrl) {
    sources.push('/static/plant-placeholder.svg');
    return [...new Set(sources)];
  }
  const isPlaceholder = /(?:noimage|imageunavailable|\/image(?:_0)?\.jpg|\/static\/placeholders\/|aspca-logo-square\.png|\/static\/plant-placeholder\.svg|placeholder|default|no-image|example\.com)/i.test(imageUrl);
  if (!isPlaceholder) {
    sources.push(imageUrl);
  } else {
    sources.push('/static/plant-placeholder.svg');
  }
  return [...new Set(sources)];
}

function plantGalleryItems(plant) {
  const colourProfile = getPlantColourDetails(plant);
  const items = Array.isArray(colourProfile.galleryImages) ? colourProfile.galleryImages : [];
  if (items.length) {
    return items
      .map(item => ({
        label: item.label || item.title || 'Photo',
        image_url: item.image_url || '',
        source_url: /^https?:\/\//i.test(String(item.source_url || '').trim()) ? item.source_url : (String(plant?.source_url || '').trim()),
        source_name: item.source_name || 'Source',
      }))
      .filter(item => item.image_url && item.source_url);
  }
  const sources = imageSources(plant);
  return sources.slice(0, 3).map((image_url, index) => ({
    label: index === 0 ? 'Main photo' : `Photo ${index + 1}`,
    image_url,
    source_url: plant.source_url || '',
    source_name: sourceConfidence(plant).label.replace('Source: ', ''),
  }));
}

function plantImageError(image) {
  const sources = JSON.parse(image.dataset.sources || '[]');
  const next = sources.indexOf(image.currentSrc || image.src) + 1;
  if (next < sources.length) { image.src = sources[next]; return; }
  image.onerror = null; image.hidden = true; image.nextElementSibling.hidden = false; image.nextElementSibling.nextElementSibling.hidden = false;
}

function plantImageLoaded(image) {
  // Detect nearly-uniform placeholder/blank images loaded through the proxy.
  try {
    if (!image || !image.complete || image.naturalWidth < 2 || image.naturalHeight < 2) {
      plantImageError(image);
      return;
    }
    const canvas = document.createElement('canvas');
    canvas.width = 32;
    canvas.height = 32;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    if (!context) return;
    context.drawImage(image, 0, 0, 32, 32);
    const data = context.getImageData(0, 0, 32, 32).data;
    let total = 0;
    let totalSq = 0;
    let alphaLow = 0;
    for (let i = 0; i < data.length; i += 4) {
      const r = data[i];
      const g = data[i + 1];
      const b = data[i + 2];
      const a = data[i + 3];
      const luma = 0.2126 * r + 0.7152 * g + 0.0722 * b;
      total += luma;
      totalSq += luma * luma;
      if (a < 8) alphaLow += 1;
    }
    const pixels = data.length / 4;
    const mean = total / pixels;
    const variance = Math.max(0, (totalSq / pixels) - (mean * mean));
    const stddev = Math.sqrt(variance);
    const transparentRatio = alphaLow / pixels;
    // Treat near-flat visuals (white/mint/solid blocks) and mostly transparent images as broken.
    if (transparentRatio > 0.98 || stddev < 3.2) plantImageError(image);
  } catch (_) {
    // Cross-origin pixels may be unreadable; keep image if it rendered.
  }
}

// Debounce helper for search input
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

function delimitedFromRows(rows, includeHeaders = true, separator = ',') {
  if (!rows.length) return '';
  const keys = Object.keys(rows[0]);
  const escapeCell = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const body = rows.map(row => keys.map(key => escapeCell(row[key])).join(separator));
  return `${includeHeaders ? `${keys.map(escapeCell).join(separator)}\n` : ''}${body.join('\n')}`;
}

function markdownFromRows(rows, includeHeaders = true) {
  if (!rows.length) return '';
  const keys = Object.keys(rows[0]);
  const escapeCell = value => String(value ?? '').replaceAll('|', '\\|').replaceAll('\n', ' ');
  const header = `| ${keys.map(escapeCell).join(' | ')} |`;
  const divider = `| ${keys.map(() => '---').join(' | ')} |`;
  const body = rows.map(row => `| ${keys.map(key => escapeCell(row[key])).join(' | ')} |`);
  return `${includeHeaders ? `${header}\n${divider}\n` : ''}${body.join('\n')}`;
}

function htmlTableFromRows(rows, includeHeaders = true) {
  if (!rows.length) return '';
  const keys = Object.keys(rows[0]);
  const header = includeHeaders ? `<thead><tr>${keys.map(key => `<th>${escapeHtml(key)}</th>`).join('')}</tr></thead>` : '';
  const body = `<tbody>${rows.map(row => `<tr>${keys.map(key => `<td>${escapeHtml(row[key] ?? '')}</td>`).join('')}</tr>`).join('')}</tbody>`;
  return `<!doctype html><html><head><meta charset="utf-8"><title>Plants export</title><style>body{font-family:Arial,sans-serif;padding:16px}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d6d3d1;padding:6px;text-align:left;font-size:12px}th{background:#f1f5f9}</style></head><body><table>${header}${body}</table></body></html>`;
}

function exportPayloadFromRows(rows, format, includeHeaders = true) {
  if (!rows.length) return { text: '', mime: 'text/plain' };
  if (format === 'json') return { text: JSON.stringify(rows, null, 2), mime: 'application/json' };
  if (format === 'ndjson') return { text: rows.map(row => JSON.stringify(row)).join('\n'), mime: 'application/x-ndjson' };
  if (format === 'markdown') return { text: markdownFromRows(rows, includeHeaders), mime: 'text/markdown;charset=utf-8' };
  if (format === 'html') return { text: htmlTableFromRows(rows, includeHeaders), mime: 'text/html;charset=utf-8' };
  if (format === 'tsv') return { text: delimitedFromRows(rows, includeHeaders, '\t'), mime: 'text/tab-separated-values;charset=utf-8' };
  return { text: delimitedFromRows(rows, includeHeaders, ','), mime: 'text/csv;charset=utf-8' };
}

// Improved search and filtering functions
function tokenizeText(text) {
  return text.toLowerCase()
    .split(/[\s\-,;:()[\]{}]+/)
    .filter(token => token.length > 1);
}

function escapeRegExp(text) {
  return String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normaliseToken(token) {
  return String(token || '').toLowerCase().replace(/[^a-z0-9]/g, '');
}

function applySearchPhraseAliases(text) {
  let result = String(text || '').trim();
  if (!result) return '';
  const aliases = {
    'lilly': 'lily',
    'lillies': 'lily',
    'cat mint': 'catmint',
    'catmint plant': 'catmint',
    'calla lilly': 'black calla',
    'calla lily': 'black calla',
    'black calla lilly': 'black calla',
    'black calla lily': 'black calla',
    'lily of the valley': 'lily of the valley',
    'lily-of-the-valley': 'lily of the valley',
    'fountain grass': 'fountain grass',
    'feather grass': 'feather grass',
    'ornamental grass': 'ornamental grass',
    'sweet pea': 'sweet pea',
    'sweetpea': 'sweet pea',
    'white lily': 'white lily',
    'dog safe': 'dog safe',
    'pet safe': 'pet safe',
    'non toxic': 'non toxic',
    'nontoxic': 'non toxic'
  };
  const entries = Object.entries(aliases).sort((a, b) => b[0].length - a[0].length);
  for (const [alias, replacement] of entries) {
    const pattern = new RegExp(`\\b${escapeRegExp(alias)}\\b`, 'gi');
    result = result.replace(pattern, replacement);
  }
  return result;
}

function normalizeSearchText(value) {
  let raw = String(value || '').trim();
  if (!raw) return '';
  raw = raw.normalize('NFKD').replace(/[\u0300-\u036f]/g, '');
  raw = raw.toLowerCase().replace(/[’']/g, "'");
  raw = applySearchPhraseAliases(raw);
  raw = raw.replace(/[_/\\-]+/g, ' ');
  raw = raw.replace(/[^a-z0-9\s]/g, ' ');
  raw = raw.replace(/\s+/g, ' ').trim();
  return raw;
}

function getSearchLearningGraph() {
  try {
    const raw = localStorage.getItem('plantSearchLearningGraph');
    if (!raw) return { aliases: {}, zeroResults: [], accepted: [] };
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return { aliases: {}, zeroResults: [], accepted: [] };
    return {
      aliases: parsed.aliases && typeof parsed.aliases === 'object' ? parsed.aliases : {},
      zeroResults: Array.isArray(parsed.zeroResults) ? parsed.zeroResults : [],
      accepted: Array.isArray(parsed.accepted) ? parsed.accepted : []
    };
  } catch (_) {
    return { aliases: {}, zeroResults: [], accepted: [] };
  }
}

function persistSearchLearningGraph(graph) {
  try {
    localStorage.setItem('plantSearchLearningGraph', JSON.stringify(graph));
  } catch (_) {
    // Ignore localStorage write failures gracefully.
  }
}

function applySearchLearningAliases(value) {
  const rawValue = String(value || '').trim();
  if (!rawValue) return '';
  const graph = getSearchLearningGraph();
  const lookupKey = normalizeSearchText(rawValue);
  if (!lookupKey) return rawValue;
  const learnedMatch = graph.aliases[lookupKey];
  if (learnedMatch) return normalizeSearchText(learnedMatch);
  return rawValue;
}

function normalizeSearchQuery(value) {
  const raw = normalizeSearchText(value);
  if (!raw) return '';
  const learned = applySearchLearningAliases(raw);
  return normalizeSearchText(learned || raw);
}

function addApprovedSearchAlias(rawAlias, canonicalName) {
  const alias = String(rawAlias || '').trim();
  const canonical = String(canonicalName || '').trim();
  if (!alias || !canonical) return null;

  const graph = getSearchLearningGraph();
  const aliasKey = normalizeSearchQuery(alias);
  const canonicalKey = normalizeSearchQuery(canonical);
  if (!aliasKey || !canonicalKey || aliasKey === canonicalKey) return canonical;

  graph.aliases[aliasKey] = canonicalKey;
  graph.accepted = Array.isArray(graph.accepted) ? graph.accepted : [];
  const exists = graph.accepted.some(entry => String(entry.normalized || '').toLowerCase() === aliasKey && String(entry.canonicalNormalized || '').toLowerCase() === canonicalKey);
  if (!exists) {
    graph.accepted.push({
      alias,
      canonical,
      normalized: aliasKey,
      canonicalNormalized: canonicalKey,
      at: new Date().toISOString()
    });
  }
  if (graph.accepted.length > 60) graph.accepted = graph.accepted.slice(-60);
  persistSearchLearningGraph(graph);
  spellcheckDictionary.common_misspellings[aliasKey] = canonical;
  return canonical;
}

function collectSearchSuggestionCandidates(query, sourcePlants = plants) {
  const normalizedQuery = normalizeSearchQuery(query || '');
  if (!normalizedQuery) return [];
  const names = sourcePlants.flatMap(plant => getPlantSearchNames(plant));
  const seen = new Set();
  const scored = names.map(name => {
    const label = String(name || '').trim();
    if (!label) return null;
    const normalizedLabel = normalizeSearchQuery(label);
    if (!normalizedLabel || normalizedLabel === normalizedQuery) return null;

    let score = 0;
    if (normalizedLabel === normalizedQuery) score = 100;
    else if (normalizedLabel.includes(normalizedQuery) || normalizedQuery.includes(normalizedLabel)) score = 80;
    else if (isCloseWordMatch(normalizedQuery, normalizedLabel)) score = 70;
    else {
      const distance = levenshteinDistance(normalizedQuery, normalizedLabel, Math.min(3, Math.max(1, Math.floor(normalizedLabel.length / 5))));
      if (distance <= 2) score = 60;
    }

    if (!score) return null;
    if (seen.has(normalizedLabel)) return null;
    seen.add(normalizedLabel);
    return { label, score };
  }).filter(Boolean).sort((a, b) => b.score - a.score);

  return scored.slice(0, 4).map(item => item.label);
}

function expandAliasVariant(value) {
  const variants = new Set();
  const base = normalizeSearchQuery(value);
  if (!base) return [];
  variants.add(base);
  variants.add(base.replace(/\s+/g, ''));
  variants.add(base.replace(/\s+/g, '-'));
  const parts = base.split(/\s+/).filter(Boolean);
  if (parts.length > 1) {
    const singular = parts.map(part => {
      if (part.endsWith('ies') && part.length > 4) return `${part.slice(0, -3)}y`;
      if (part.endsWith('ses') && part.length > 4) return part.slice(0, -2);
      if (part.endsWith('s') && part.length > 3) return part.slice(0, -1);
      return part;
    }).join(' ');
    if (singular) variants.add(singular);
    variants.add(parts.join(''));
    variants.add(parts.join('-'));
  }
  return [...variants].filter(Boolean);
}

function buildPlantAliasIndex(plant) {
  const values = [];
  if (plant?.name) values.push(String(plant.name));
  if (plant?.scientific_name) values.push(String(plant.scientific_name));
  if (plant?.category) values.push(String(plant.category));
  const synonyms = Array.isArray(getPlantSynonyms(plant)) ? getPlantSynonyms(plant) : [];
  values.push(...synonyms);
  const aliasIndex = new Set();
  values.forEach(value => {
    const tokens = expandAliasVariant(value);
    tokens.forEach(token => aliasIndex.add(token));
  });
  return [...aliasIndex];
}

function applySpellcheckToQuery(value) {
  const rawText = String(value || '').trim();
  if (!rawText) return '';

  return rawText
    .split(/\s+/)
    .map(part => {
      const clean = normalizeSearchQuery(part);
      if (!clean) return '';
      return spellcheckDictionary.common_misspellings[clean] || part;
    })
    .filter(Boolean)
    .join(' ');
}

async function parseJsonResponse(response, label = 'Request') {
  const text = await response.text();
  if (!text) return {};
  const type = (response.headers.get('content-type') || '').toLowerCase();
  if (type && !type.includes('json') && !type.includes('javascript')) {
    const preview = text.replace(/\s+/g, ' ').trim().slice(0, 180);
    throw new Error(`${label} returned non-JSON content: ${preview || 'empty response'}`);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    const preview = text.replace(/\s+/g, ' ').trim().slice(0, 180);
    throw new Error(`${label} returned invalid JSON: ${preview || 'empty response'}`);
  }
}

async function loadSpellcheckDictionary() {
  try {
    const response = await fetch('/static/plant_spellcheck.json', { cache: 'force-cache' });
    if (!response.ok) return;
    const data = await parseJsonResponse(response, 'Spellcheck dictionary');
    const mapping = {};
    const source = data && typeof data === 'object' ? (data.common_misspellings || data.misspellings || {}) : {};
    const phrases = data && typeof data === 'object' ? (data.common_phrase_aliases || {}) : {};
    const merged = { ...source, ...phrases };
    Object.entries(merged).forEach(([misspelling, correction]) => {
      const cleanKey = normalizeSearchQuery(misspelling);
      const cleanValue = String(correction || '').trim();
      if (cleanKey && cleanValue) mapping[cleanKey] = cleanValue;
    });

    const learnedGraph = getSearchLearningGraph();
    Object.entries(learnedGraph.aliases || {}).forEach(([aliasKey, canonicalKey]) => {
      const cleanedKey = normalizeSearchQuery(aliasKey);
      const cleanedValue = normalizeSearchQuery(canonicalKey);
      if (cleanedKey && cleanedValue) mapping[cleanedKey] = cleanedValue;
    });

    spellcheckDictionary = { common_misspellings: mapping };
  } catch (_) {
    spellcheckDictionary = { common_misspellings: {} };
  }
}

function getPlantSearchNames(plant) {
  const names = [];
  if (plant?.name) names.push(String(plant.name));
  if (plant?.scientific_name) names.push(String(plant.scientific_name));
  const synonyms = getPlantSynonyms(plant) || [];
  names.push(...synonyms);
  return [...new Set(names.map(value => String(value || '').trim()).filter(Boolean))];
}

function inferNaturalLanguageIntent(query) {
  const normalized = normalizeSearchQuery(query || '');
  if (!normalized) return null;
  const intent = { safety: null, category: null, placement: null, colour: null, shadeRequired: false };
  if (/(dog safe|pet safe|safe for dogs|safe for pets|non toxic|non-toxic|nontoxic)/.test(normalized)) {
    intent.safety = 'Non-toxic to dogs';
  }
  if (/(grass|ornamental grass|fountain grass|feather grass|bamboo)/.test(normalized)) intent.category = 'grasses';
  if (/(flower|flowers|bloom|blossom)/.test(normalized)) intent.category = 'flowers';
  if (/(herb|herbs|sage|thyme|mint|rosemary)/.test(normalized)) intent.category = 'herbs';
  if (/(fruit|berries|strawberry|blueberry)/.test(normalized)) intent.category = 'fruit';
  if (/(vegetable|veggie|veg|lettuce|carrot|bean)/.test(normalized)) intent.category = 'vegetables';
  if (/(shade|shady|part shade|partial shade|indoor)/.test(normalized)) {
    intent.placement = 'shade';
    intent.shadeRequired = true;
  }
  if (/(outside|outdoor|garden)/.test(normalized)) intent.placement = 'outdoor';
  if (/(sun|full sun|bright sun)/.test(normalized)) intent.placement = 'sun';
  if (/(purple|violet|lavender)/.test(normalized)) intent.colour = 'purple';
  if (/(red|crimson|scarlet)/.test(normalized)) intent.colour = 'red';
  if (/(green|lime)/.test(normalized)) intent.colour = 'green';
  if (/(yellow|gold)/.test(normalized)) intent.colour = 'yellow';
  return Object.values(intent).some(value => value !== null && value !== false) ? intent : null;
}

function findSpellcheckCorrection(query, sourcePlants = plants) {
  const rawValue = String(query || '').trim();
  if (!rawValue) return null;

  const queryKey = normalizeSearchQuery(rawValue);
  if (!queryKey || queryKey.length < 3) return null;

  const learnedAliases = getSearchLearningGraph().aliases || {};
  const direct = spellcheckDictionary.common_misspellings[queryKey] || learnedAliases[queryKey];
  if (direct) return String(direct).trim();

  const names = sourcePlants.flatMap(plant => getPlantSearchNames(plant));
  const scoredMatches = names
    .map(name => {
      const label = String(name || '').trim();
      const key = normalizeSearchQuery(label);
      if (!label || !key || key === queryKey) return null;

      if (label.toLowerCase() === rawValue.toLowerCase()) return null;

      const tokenMatches = label.toLowerCase().split(/\s+/).filter(Boolean).some(part => {
        const partKey = normalizeSearchQuery(part);
        return partKey && (partKey === queryKey || isCloseWordMatch(queryKey, partKey));
      });

      if (!tokenMatches && !(key.includes(queryKey) || queryKey.includes(key))) {
        const distance = levenshteinDistance(queryKey, key, Math.min(2, Math.max(1, Math.floor(key.length / 5))));
        if (distance > (key.length > 9 ? 2 : 1)) return null;
      }

      const score = label.split(/\s+/).length > 1 ? 80 : 90;
      return { label, score };
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);

  if (scoredMatches.length) return scoredMatches[0].label;

  const learnedCandidates = collectSearchSuggestionCandidates(rawValue, sourcePlants);
  return learnedCandidates[0] || null;
}

function updateSearchSuggestion() {
  const input = document.querySelector('#plant-search');
  const container = document.querySelector('#search-correction');
  const button = document.querySelector('#search-correction-button');
  if (!input || !container || !button) return;

  const query = String(input.value || '').trim();
  const suggestion = query ? findSpellcheckCorrection(query, plants) : null;
  const isVisible = !!suggestion && suggestion.toLowerCase() !== query.toLowerCase();

  container.classList.toggle('hidden', !isVisible);
  button.textContent = suggestion || '';
  button.dataset.correction = suggestion || '';
}

function recordZeroResultSearch(query) {
  const raw = String(query || '').trim();
  if (!raw) return;
  try {
    const key = 'plantZeroResultSearches';
    const previous = JSON.parse(localStorage.getItem(key) || '[]');
    const next = Array.isArray(previous) ? previous : [];
    const item = { query: raw, normalized: normalizeSearchQuery(raw), at: new Date().toISOString() };
    const existing = next.find(entry => entry.normalized === item.normalized && entry.query.toLowerCase() === raw.toLowerCase());
    if (!existing) {
      next.push(item);
      if (next.length > 80) next.shift();
      localStorage.setItem(key, JSON.stringify(next));
    }

    const graph = getSearchLearningGraph();
    graph.zeroResults = next;
    persistSearchLearningGraph(graph);
  } catch (_) {
    // Ignore localStorage failures gracefully.
  }
}

function acceptSearchSuggestion(suggestedQuery) {
  const input = document.querySelector('#plant-search');
  const query = String(input?.value || '').trim();
  const suggestion = String(suggestedQuery || '').trim();
  if (!query || !suggestion) return;

  const accepted = addApprovedSearchAlias(query, suggestion);
  if (!accepted) return;

  if (input) {
    input.value = accepted;
  }
  filters.search = accepted;
  renderPlants();
}

function stemVariant(token) {
  const value = normaliseToken(token);
  if (!value) return value;
  if (value.endsWith('lly') && value.length > 4) return value.slice(0, -1);
  if (value.endsWith('ies') && value.length > 3) return `${value.slice(0, -3)}y`;
  if (value.endsWith('es') && value.length > 3) return value.slice(0, -2);
  if (value.endsWith('s') && value.length > 3) return value.slice(0, -1);
  if (value.endsWith('y') && value.length > 2) return `${value.slice(0, -1)}ies`;
  return value;
}

function levenshteinDistance(a, b, maxDistance = 2) {
  if (a === b) return 0;
  if (!a || !b) return Math.max(a.length, b.length);
  if (Math.abs(a.length - b.length) > maxDistance) return maxDistance + 1;

  const prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  const curr = new Array(b.length + 1);

  for (let i = 1; i <= a.length; i++) {
    curr[0] = i;
    let rowMin = curr[0];
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(
        prev[j] + 1,
        curr[j - 1] + 1,
        prev[j - 1] + cost
      );
      rowMin = Math.min(rowMin, curr[j]);
    }
    if (rowMin > maxDistance) return maxDistance + 1;
    for (let j = 0; j <= b.length; j++) prev[j] = curr[j];
  }
  return prev[b.length];
}

function isCloseWordMatch(term, token) {
  const a = normaliseToken(term);
  const b = normaliseToken(token);
  if (!a || !b) return false;
  if (a === b) return true;
  if (stemVariant(a) === b || stemVariant(b) === a || stemVariant(a) === stemVariant(b)) return true;
  if (Math.min(a.length, b.length) < 4) return false;
  const threshold = Math.max(a.length, b.length) >= 9 ? 2 : 1;
  return levenshteinDistance(a, b, threshold) <= threshold;
}

// Season filtering helper
function isPlantBloomingInSeason(plant, season) {
  if (season === 'all') return true;
  const seasonality = plant.seasonality || {};
  const bloomSummary = `${String(plant?.blooming_period || '').toLowerCase()} ${String(seasonality.blooming_period || '').toLowerCase()} ${String(seasonality.notes || '').toLowerCase()}`;
  const hasSeasonalityData = !!plant.seasonality && (
    seasonality.year_round === true ||
    (Array.isArray(seasonality.peak_bloom_months) && seasonality.peak_bloom_months.length > 0) ||
    Boolean(seasonality.blooming_period) ||
    Boolean(seasonality.notes)
  );
  if (season === 'all-year') {
    if (!hasSeasonalityData) return true;
    if (seasonality.year_round === true) return true;
    const peakMonths = Array.isArray(seasonality.peak_bloom_months) ? seasonality.peak_bloom_months : [];
    const seasons = {
      spring: [3, 4, 5],
      summer: [6, 7, 8],
      autumn: [9, 10, 11],
      winter: [12, 1, 2],
    };
    const coveredSeasons = Object.values(seasons).filter(months => peakMonths.some(month => months.includes(month))).length;
    if (coveredSeasons >= 3) return true;
    if (peakMonths.length >= 8) return true;
    return /all year|year-round|year round|continuous|everbloom/i.test(bloomSummary);
  }
  if (!seasonality) return true; // No seasonality data, include it

  const seasonMonths = {
    'spring': [3, 4, 5],
    'summer': [6, 7, 8],
    'autumn': [9, 10, 11],
    'winter': [12, 1, 2]
  };
  
  const months = seasonMonths[season] || [];
  const peakMonths = seasonality.peak_bloom_months || [];
  
  // Check if plant blooms during this season
  return peakMonths.some(m => months.includes(m));
}

function calculateSearchScore(plant, searchTerms) {
  if (!searchTerms || searchTerms.length === 0) return 1;
  
  const synonymText = getPlantSynonyms(plant).join(' ');
  const searchText = `${plant.name} ${plant.scientific_name} ${synonymText} ${getPlantDescription(plant)} ${plant.category}`.toLowerCase();
  const normalizedSearchText = normalizeSearchQuery(searchText);
  const primaryNameText = `${plant.name} ${plant.scientific_name}`.toLowerCase();
  const normalizedName = String(plant.name || '').toLowerCase().replace(/\s+\d+$/, '').trim();
  const normalizedScientific = String(plant.scientific_name || '').toLowerCase().trim();
  const plantTokens = tokenizeText(searchText);
  const primaryNameTokens = tokenizeText(primaryNameText);
  const aliasIndex = new Set(buildPlantAliasIndex(plant).map(value => normalizeSearchQuery(value)));
  const intent = inferNaturalLanguageIntent(searchTerms.join(' '));
  
  let score = 0;
  let matchedTerms = 0;
  
  for (const term of searchTerms) {
    const normalizedTerm = normalizeSearchQuery(term);
    if (!normalizedTerm) continue;
    let termScore = 0;
    
    if (plant.name.toLowerCase() === normalizedTerm) {
      termScore = 100;
    }
    else if (normalizedName.match(new RegExp(`\\b${escapeRegExp(normalizedTerm)}\\b`))) {
      termScore = 80;
    }
    else if (normalizedScientific === normalizedTerm) {
      termScore = 60;
    }
    else if (normalizedScientific.match(new RegExp(`\\b${escapeRegExp(normalizedTerm)}\\b`))) {
      termScore = 50;
    }
    else if (aliasIndex.has(normalizedTerm)) {
      termScore = 85;
    }
    else if ([...aliasIndex].some(alias => alias.includes(normalizedTerm) || normalizedTerm.includes(alias))) {
      termScore = 65;
    }
    else if (plantTokens.some(token => token.startsWith(normalizedTerm))) {
      termScore = 30;
    }
    else if (normalizedSearchText.includes(normalizedTerm)) {
      termScore = 20;
    }
    else if (primaryNameTokens.some(token => isCloseWordMatch(normalizedTerm, token))) {
      termScore = 15;
    }
    else if (normalizedTerm.length > 2) {
      const fuzzyMatches = plantTokens.filter(token => {
        const matches = Math.min(normalizedTerm.length, token.length);
        let matchCount = 0;
        for (let i = 0; i < matches; i++) {
          if (normalizedTerm[i] === token[i]) matchCount++;
        }
        return matchCount >= Math.ceil(matches * 0.6);
      });
      if (fuzzyMatches.length > 0) termScore = 10;
    }
    
    if (intent && intent.category && plant.category === intent.category) termScore += 25;
    if (intent && intent.safety === 'Non-toxic to dogs' && plant.safety_status === 'Non-toxic to dogs') termScore += 30;
    if (intent && intent.colour && plant.colour_details && String(plant.colour_details).toLowerCase().includes(intent.colour)) termScore += 20;
    if (intent && intent.shadeRequired) {
      const shadeText = `${plant.sun_exposure || ''} ${plant.light || ''} ${getPlantDescription(plant) || ''}`.toLowerCase();
      if (shadeText.includes('shade') || shadeText.includes('partial shade')) termScore += 15;
    }
    
    if (termScore > 0) {
      score += termScore;
      matchedTerms++;
    }
  }
  
  if (matchedTerms === searchTerms.length && matchedTerms > 0) {
    score *= (1 + 0.5 * (matchedTerms - 1));
  }
  
  return matchedTerms === searchTerms.length ? score : 0;
}

function matchesSearch(plant, searchQuery) {
  if (!searchQuery || searchQuery.trim() === '') return true;
  const normalizedQuery = normalizeSearchQuery(searchQuery);
  const searchTerms = tokenizeText(normalizedQuery);
  if (!searchTerms.length) return true;
  const intent = inferNaturalLanguageIntent(searchQuery);
  if (intent && intent.safety === 'Non-toxic to dogs' && plant.safety_status === 'Non-toxic to dogs') return true;
  if (intent && intent.category && plant.category === intent.category) return true;
  return calculateSearchScore(plant, searchTerms) > 0;
}

function getPlantPlacementTags(plant) {
  const value = plant?.indoor_outdoor;
  const tokens = Array.isArray(value) ? value : String(value || '').split(/[,|/;]/g);
  const tags = [];
  tokens.forEach(token => {
    const text = String(token || '').trim().toLowerCase();
    if (!text) return;
    if (text.includes('indoor') || text.includes('houseplant') || text.includes('house plant')) tags.push('indoor');
    if (text.includes('outdoor') || text.includes('garden')) tags.push('outdoor');
  });
  const deduped = [...new Set(tags)];
  if (!deduped.length) return ['outdoor'];
  if (deduped.includes('indoor') && deduped.includes('outdoor')) return ['indoor', 'outdoor'];
  return deduped;
}

function getPlantDescription(plant) {
  const raw = String(plant?.description || '').trim();
  if (raw) return raw;

  const parts = [
    plant?.scientific_name ? `${plant.scientific_name}.` : '',
    plant?.category ? `A ${toSentence(String(plant.category).replace(/_/g, ' '))} plant.` : '',
    plant?.safety_status ? `Safety status: ${plant.safety_status}.` : '',
    'Suitable for a well-planned, pet-aware garden.'
  ].filter(Boolean);

  return parts.join(' ');
}

function matchesPlacementFilter(plant, placement) {
  const selected = Array.isArray(placement) ? placement : [placement];
  const chosen = selected.filter(Boolean);
  if (!chosen.length || chosen.length >= 2) return true;
  const tags = getPlantPlacementTags(plant);
  return chosen.some(item => tags.includes(item));
}

function selectedHabitats() {
  const valid = new Set(['indoor', 'outdoor']);
  const selected = (filters.habitats || []).filter(item => valid.has(item));
  if (!selected.length) return ['indoor', 'outdoor'];
  return [...new Set(selected)];
}

function setHabitatChipState() {
  const selected = new Set(selectedHabitats());
  document.querySelectorAll('[data-habitat-chip]').forEach(button => {
    const isActive = selected.has(button.dataset.habitatChip);
    button.classList.toggle('is-active', isActive);
    button.setAttribute('aria-pressed', String(isActive));
  });
}

function sourceConfidence(plant) {
  const explicit = String(plant?.source_confidence || '').toLowerCase();
  const confidenceLabel = value => `Source: ${value.charAt(0).toUpperCase()}${value.slice(1)}`;
  if (['high', 'medium', 'low'].includes(explicit)) {
    return { label: confidenceLabel(explicit), level: explicit };
  }
  const source = String(plant?.source_url || '').toLowerCase();
  if (!source) return { label: confidenceLabel('low'), level: 'low' };
  if (source.includes('aspca.org')) return { label: confidenceLabel('high'), level: 'high' };
  if (source.includes('oneclickplants.co.uk') || source.includes('purepetfood.com') || source.includes('animalemergencyservice.com.au')) return { label: confidenceLabel('medium'), level: 'medium' };
  return { label: confidenceLabel('low'), level: 'low' };
}

function sourceLinkLabel(plant) {
  const source = String(plant?.source_url || '');
  if (/aspca\.org/i.test(source)) return plant?.source_status ? 'Check ASPCA database' : 'View ASPCA listing';
  return 'View source reference';
}

const TREE_KEYWORDS = [
  'tree', 'shade tree', 'orchard tree', 'fruit tree', 'flowering tree', 'conifer',
  'evergreen tree', 'deciduous tree', 'shade canopy', 'woody perennial',
  'maple', 'oak', 'pine', 'spruce', 'fir', 'cedar', 'birch', 'willow', 'elm',
  'sycamore', 'juniper', 'cypress', 'sequoia', 'redwood', 'eucalyptus', 'acacia',
  'palm', 'poplar', 'aspen', 'beech', 'hornbeam', 'hawthorn', 'dogwood', 'magnolia',
  'linden', 'chestnut', 'ash', 'holly', 'rowan', 'larch', 'yew', 'arborvitae',
  'hickory', 'shellbark', 'shagbark', 'walnut', 'pecan',
  'acer', 'quercus', 'pinus', 'picea', 'abies', 'cedrus', 'betula', 'salix', 'ulmus',
  'platanus', 'juniperus', 'cupressus', 'sequoiadendron', 'fraxinus', 'ilex', 'sorbus',
  'malus', 'pyrus', 'ficus', 'populus', 'fagus', 'carpinus', 'crataegus', 'cornus',
  'tilia', 'aesculus', 'washingtonia', 'morus', 'carya', 'juglans'
];

function getTreeClassification(plant) {
  const plantText = [plant?.name, plant?.scientific_name, plant?.description, plant?.growth_habit, plant?.category].filter(Boolean).join(' ').toLowerCase();
  const normalizedPlantText = ` ${plantText.replace(/[^a-z0-9]+/gi, ' ').trim()} `;
  const normalizedName = ` ${String(plant?.name || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()} `;
  const isTreeKeyword = TREE_KEYWORDS.some(keyword => normalizedPlantText.includes(` ${keyword.toLowerCase()} `));
  const isExplicitLargePlant =
    normalizedName.includes(' algaroba ') ||
    normalizedName.includes(' banana plant ') ||
    (normalizedName.trim() === 'banana');
  return { isTree: isTreeKeyword || isExplicitLargePlant, label: isExplicitLargePlant ? 'Large plant' : 'Tree' };
}

function renderPlants() {
  const hideTreesCheckbox = document.querySelector('#hide-trees-filter');
  if (hideTreesCheckbox) hideTreesCheckbox.checked = !!filters.hideTrees;
  const showToxicCheckbox = document.querySelector('#show-toxic-filter');
  if (showToxicCheckbox) showToxicCheckbox.checked = !!filters.showToxic;
  const lifecycleSelect = document.querySelector('#lifecycle-filter');
  if (lifecycleSelect) lifecycleSelect.value = filters.lifecycle;
  const lightFilter = document.querySelector('#light-filter');
  if (lightFilter) lightFilter.value = filters.light;
  const heightFilter = document.querySelector('#height-filter');
  if (heightFilter) heightFilter.value = filters.height;
  const spreadFilter = document.querySelector('#spread-filter');
  if (spreadFilter) spreadFilter.value = filters.spread;
  const tendernessFilter = document.querySelector('#tenderness-filter');
  if (tendernessFilter) tendernessFilter.value = filters.tenderness;
  const containerFilter = document.querySelector('#container-filter');
  if (containerFilter) containerFilter.value = filters.container;
  const wateringFilter = document.querySelector('#watering-filter');
  if (wateringFilter) wateringFilter.value = filters.watering;
  const pollinatorFilter = document.querySelector('#pollinator-filter');
  if (pollinatorFilter) pollinatorFilter.value = filters.pollinator;
  const fragranceFilter = document.querySelector('#fragrance-filter');
  if (fragranceFilter) fragranceFilter.value = filters.fragrance;
  const habitFilter = document.querySelector('#habit-filter');
  if (habitFilter) habitFilter.value = filters.habit;
  setHabitatChipState();
  
  // Parse search terms
  const correctedSearch = applySpellcheckToQuery(filters.search);
  const searchTerms = correctedSearch ? tokenizeText(correctedSearch) : [];
  
  const sourcePlants = filters.reviewOnly ? plantReviewQueue : plants;
  const visible = sourcePlants
    .filter(plant => {
      // Category filter
      if (category !== 'all' && plant.category !== category) return false;
      
      const hasSearch = !!filters.search;
      const searchMatched = !hasSearch || matchesSearch(plant, filters.search);
      if (hasSearch && !searchMatched) return false;

      if (filters.reviewOnly) {
        if (filters.safety !== 'all' && plant.safety_status !== filters.safety) return false;
        return true;
      }
      
      // Safety filter
      if (filters.safety !== 'all' && plant.safety_status !== filters.safety) return false;

      // Hide confirmed toxic plants by default unless explicitly shown, safety-filtered, or directly searched.
      const isRisky = isRiskySafetyStatus(plant.safety_status);
      const explicitSafetySelection = filters.safety === 'Toxic' || filters.safety === 'May be Toxic';
      if (isRisky && !filters.showToxic && !explicitSafetySelection && !hasSearch) return false;

      // Indoor/outdoor placement filter
      if (!matchesPlacementFilter(plant, selectedHabitats())) return false;
      
      // Favorites filter
      if (filters.favorites && !favoriteIds.has(plant.id)) return false;
      
      const treeClassification = getTreeClassification(plant);
      if (filters.hideTrees && treeClassification.isTree) return false;
      
      // Climate zone filter
      if (filters.climateZone && plant.hardiness_zones_uk) {
        const zones = plant.hardiness_zones_uk.split('-').map(z => z.trim());
        const userZone = filters.climateZone.toUpperCase();
        const zoneCompatible = zones.includes(userZone) || (zones.length === 2 && (() => {
          try {
            const userNum = parseInt(userZone.replace('H', ''));
            const minNum = parseInt(zones[0].replace('H', ''));
            const maxNum = parseInt(zones[1].replace('H', ''));
            return !isNaN(userNum) && !isNaN(minNum) && !isNaN(maxNum) && minNum <= userNum && userNum <= maxNum;
          } catch (_) { return false; }
        })());
        if (!zoneCompatible) return false;
      }
       
      // Season filter
      if (filters.season !== 'all' && !isPlantBloomingInSeason(plant, filters.season)) return false;

      // Lifecycle filter
      if (!matchesLifecycleFilter(plant, filters.lifecycle)) return false;

      const lifecycleDetails = inferLifecycleDetails(plant);
      const profileOverride = getProfileOverride(plant);
      const sunlightText = [profileOverride.sun_exposure, plant.sun_exposure].flat().filter(Boolean).join(' ');
      const sizeText = matureSizeTextForPlant(plant);
      const size = parseSizeToCm(sizeText);
      const tendernessText = [profileOverride.tenderness, lifecycleDetails.tenderness].filter(Boolean).join(' ');
      const containerText = [profileOverride.container_suitability, lifecycleDetails.containerSuitability].filter(Boolean).join(' ');
      const guidance = growingGuidance[plant.category] || growingGuidance.flowers;
      const colourDetails = getPlantColourDetails(plant);
      const wateringText = [profileOverride.watering_needs, plant.watering_needs, guidance.watering].filter(Boolean).join(' ');
      const pollinatorText = [profileOverride.pollinator_value, plant.pollinator_value, inferPollinatorValue(plant)].filter(Boolean).join(' ');
      const fragranceText = [profileOverride.fragrance, plant.fragrance, inferFragrance(plant)].filter(Boolean).join(' ');
      const habitText = [profileOverride.growth_habit, plant.growth_habit, getPlantDescription(plant)].filter(Boolean).join(' ');

      if (!matchesTextFilter(sunlightText, filters.light)) return false;
      if (!colourMatchesAny(colourDetails.flowerColours, filters.flowerColour)) return false;
      if (!colourMatchesAny(colourDetails.foliageColours, filters.foliageColour)) return false;
      if (!colourPatternMatchesAny(plant, filters.colourPattern)) return false;
      if (!matchesRangeFilter(size, filters.height)) return false;
      if (!matchesRangeFilter(size, filters.spread)) return false;
      if (!matchesTextFilter(tendernessText, filters.tenderness)) return false;
      if (!matchesContainerFilter(containerText, filters.container)) return false;
      if (!matchesTraitFilter(wateringText, filters.watering, {
        dry: ['dry', 'drought', 'low water', 'xeric'],
        average: ['average', 'moderate', 'regular', 'evenly moist'],
        moist: ['moist', 'wet', 'damp', 'water loving', 'rich'],
      })) return false;
      if (!matchesTraitFilter(pollinatorText, filters.pollinator, {
        high: ['high'],
        moderate: ['moderate'],
        low: ['low'],
      })) return false;
      if (!matchesTraitFilter(fragranceText, filters.fragrance, {
        aromatic: ['aromatic', 'fragrant', 'scented', 'scent'],
        mild: ['mild', 'subtle'],
        none: ['none', 'unscented', 'not fragrant', 'no fragrance'],
      })) return false;
      if (!matchesTraitFilter(habitText, filters.habit, {
        upright: ['upright', 'erect'],
        clumping: ['clump', 'clumping', 'tuft'],
        trailing: ['trailing', 'spreading', 'sprawl'],
        spreading: ['spreading', 'creeping', 'running'],
        vining: ['vine', 'vining', 'climber', 'climbing'],
      })) return false;
        
      return true;
    })
    .sort((a, b) => {
      // Sort by search relevance if searching
      if (filters.search) {
        const scoreA = calculateSearchScore(a, searchTerms);
        const scoreB = calculateSearchScore(b, searchTerms);
        if (scoreA !== scoreB) return scoreB - scoreA;
      }
      // Then by name
      return a.name.localeCompare(b.name);
    });
   const riskyCount = sourcePlants.filter(plant => isRiskySafetyStatus(plant.safety_status)).length;
   const nonToxicTreeHiddenCount = sourcePlants.filter(plant => !isRiskySafetyStatus(plant.safety_status) && getTreeClassification(plant).isTree).length;
   const pageStart = visible.length ? ((currentPage - 1) * itemsPerPage) + 1 : 0;
   const pageEnd = Math.min(currentPage * itemsPerPage, visible.length);
   const lifecycleStatus = filters.lifecycle !== 'all' ? ` · lifecycle: ${filters.lifecycle.replace(/-/g, ' ')}` : '';
   const seasonStatus = filters.season === 'all-year' ? ' · blooming all year' : '';
   const colourStatus = [
     colourSummaryText(filters.flowerColour) ? `flower: ${colourSummaryText(filters.flowerColour)}` : '',
     colourSummaryText(filters.foliageColour) ? `foliage: ${colourSummaryText(filters.foliageColour)}` : '',
     colourSummaryText(filters.colourPattern) ? `pattern: ${colourSummaryText(filters.colourPattern)}` : '',
   ].filter(Boolean).join(' · ');
   const colourSummary = colourStatus ? ` · ${colourStatus}` : '';
   const reviewStatus = filters.reviewOnly ? ' · review queue' : '';
   status.textContent = `${visible.length} plant${visible.length === 1 ? '' : 's'} shown${visible.length ? ` · showing ${pageStart}-${pageEnd}` : ''}${filters.reviewOnly ? '' : (!filters.showToxic && filters.safety === 'all' && !filters.search ? ` · ${riskyCount} toxic hidden by default` : '')}${filters.reviewOnly ? '' : (filters.hideTrees && filters.safety === 'all' && !filters.search ? ` · ${nonToxicTreeHiddenCount} non-toxic hidden by tree filter` : '')}${seasonStatus}${lifecycleStatus}${colourSummary}${reviewStatus}`;
   lastVisiblePlants = visible;
    
  // Reset to page 1 only when the visible plant count changes (i.e., filters changed)
  if (visible.length !== previousVisibleCount) {
    currentPage = 1;
    previousVisibleCount = visible.length;
  }
  totalPages = Math.ceil(visible.length / itemsPerPage);
   
  // Generate helpful "no results" message if applicable
  let noResultsMessage = filters.reviewOnly
    ? '<div class="plants-empty-state"><p>No plants found in the broader-source review queue with your selected filters.</p></div>'
    : '<div class="plants-empty-state"><p>No plants found matching your filters.</p></div>';
  if (!visible.length && filters.search) {
    recordZeroResultSearch(filters.search);
    const suggestedQuery = findSpellcheckCorrection(filters.search, plants);
    const suggestions = [];
    if (filters.safety !== 'all') suggestions.push('safety status');
    if (selectedHabitats().length === 1) suggestions.push('placement');
    if (filters.favorites) suggestions.push('favorites');
    if (filters.hideTrees) suggestions.push('tree filter');
    if (filters.climateZone) suggestions.push('climate zone');
    if (filters.flowerColour.length || filters.foliageColour.length || filters.colourPattern.length) suggestions.push('colour');
    if (filters.reviewOnly) suggestions.push('review mode');
    if (filters.lifecycle !== 'all') suggestions.push('lifecycle');
    if (filters.watering !== 'all') suggestions.push('watering');
    if (filters.pollinator !== 'all') suggestions.push('pollinator value');
    if (filters.fragrance !== 'all') suggestions.push('fragrance');
    if (filters.habit !== 'all') suggestions.push('growth habit');

    const correctionTip = suggestedQuery && suggestedQuery.toLowerCase() !== filters.search.toLowerCase()
      ? `<li><button type="button" class="text-left font-semibold text-emerald-700 underline underline-offset-2" data-search-correction="${escapeHtml(suggestedQuery)}">Did you mean “${escapeHtml(suggestedQuery)}”?</button></li>`
      : '<li>Check your spelling</li>';
      
    noResultsMessage = `
      <div class="plants-empty-state">
        <p><strong>No plants matched your search:</strong> "${escapeHtml(filters.search)}"</p>
        <div class="mt-3">
          <p class="text-sm mb-2">Try:</p>
          <ul class="text-sm list-disc list-inside">
            ${correctionTip}
            <li>Try searching for a related word (e.g., "rose" instead of "Rosa")</li>
            <li>Try natural-language queries such as "dog safe grass" or "pet safe shade plant"</li>
            ${suggestions.length ? `<li>Clearing active filters: ${suggestions.join(', ')}</li>` : ''}
            <li><a href="#" onclick="document.querySelector('#clear-plant-filters').click(); return false;">Clear all filters</a></li>
          </ul>
        </div>
      </div>
    `;
  } else if (!visible.length) {
    noResultsMessage = `
      <div class="plants-empty-state">
        <p><strong>No plants found</strong> in this category with your selected filters.</p>
        <p class="text-sm mt-2">
          <a href="#" onclick="document.querySelector('#clear-plant-filters').click(); return false;">Clear all filters</a> to see all available plants.
        </p>
      </div>
    `;
  }

  // Paginate results
  const startIdx = (currentPage - 1) * itemsPerPage;
  const endIdx = startIdx + itemsPerPage;
  const pageItems = visible.slice(startIdx, endIdx);
  lastPagePlants = pageItems;
  grid.classList.toggle('plant-grid-list', plantDisplayMode === 'list');
   
  if (filters.reviewOnly) {
    grid.innerHTML = visible.length ? pageItems.map(plant => renderReviewQueueCard(plant)).join('') : noResultsMessage;
    grid.querySelectorAll('[data-review-action]').forEach(button => {
      button.addEventListener('click', async () => {
        const action = button.dataset.reviewAction;
        const plantId = button.dataset.plantId;
        if (!action || !plantId) return;
        button.disabled = true;
        button.textContent = action === 'approve' ? 'Approving...' : 'Rejecting...';
        try {
          const result = await handleReviewQueueAction(plantId, action);
          if (result.status === 'review-only') {
            const safetyLabel = normaliseSafetyStatus(result.safety_status || 'Toxic');
            await showAlert(`${safetyLabel} entries remain visibly tagged as toxic and are not promoted to the dog-safe catalogue.`, 'Review queue');
          } else {
            const safetyLabel = normaliseSafetyStatus(result.safety_status || 'Unknown');
            const message = (safetyLabel === 'Toxic' || safetyLabel === 'May be Toxic')
              ? 'Plant approved into the live catalogue and kept tagged as toxic.'
              : 'Plant approved into the live dog-safe catalogue.';
            await showAlert(action === 'approve' ? message : 'Plant rejected from the review queue.');
          }
        } catch (error) {
          await showAlert(error.message || 'Review action failed.', 'Review queue');
        } finally {
          button.disabled = false;
          if (action === 'approve') button.textContent = 'Approve';
          if (action === 'reject') button.textContent = 'Reject';
          renderPlants();
        }
      });
    });
  } else {
    grid.innerHTML = visible.length ? pageItems.map(plant => {
      const sources = imageSources(plant);
      const placement = getPlantPlacementTags(plant);
      const confidence = sourceConfidence(plant);
      const treeClassification = getTreeClassification(plant);
      const lifecycleDetails = inferLifecycleDetails(plant);
      const colourDetails = getPlantColourDetails(plant);
      const imagePosition = String(plant.image_object_position || 'center center');
      const description = getPlantDescription(plant);
      return `
    <article class="plant-card" data-plant-id="${escapeHtml(plant.id)}">
      <div class="plant-image-frame">${sources.length ? `<img src="${escapeHtml(sources[0])}" data-sources="${escapeHtml(JSON.stringify(sources))}" alt="${escapeHtml(plant.name)}" loading="eager" style="object-position: ${escapeHtml(imagePosition)};" onload="plantImageLoaded(this);" onerror="imageBrokenIds.add('${escapeHtml(plant.id)}');plantImageError(this);">` : ''}<span class="plant-image-unavailable"${sources.length ? ' hidden' : ''}>Verified photo unavailable</span><button type="button" class="find-photo-button" data-plant-id="${escapeHtml(plant.id)}">Find correct photo</button></div>
    <div class="p-5"><div class="flex items-start justify-between gap-3"><div><h3 class="text-xl font-bold text-stone-900">${escapeHtml(plant.name)}</h3><p class="scientific-name">${escapeHtml(plant.scientific_name)}</p></div><div class="flex items-center gap-2"><button type="button" class="favorite-button ${favoriteIds.has(plant.id) ? 'is-favorite' : ''}" data-favorite-id="${escapeHtml(plant.id)}" aria-label="${favoriteIds.has(plant.id) ? 'Remove from' : 'Add to'} favourites">&#9733;</button><span class="safety-badge ${plant.safety_status === 'Toxic' ? 'safety-toxic' : plant.safety_status === 'May be Toxic' ? 'safety-may-be-toxic' : ''}">${escapeHtml(plant.safety_status)}</span></div></div><div class="mt-2 flex flex-wrap gap-2">${placement.map(tag => `<span class="placement-badge">${escapeHtml(tag)}</span>`).join('')}${treeClassification.isTree ? `<span class="plant-type-badge">${escapeHtml(treeClassification.label)}</span>` : ''}<span class="plant-type-badge">${escapeHtml(lifecycleDetails.label)}</span><span class="source-confidence-badge source-confidence-${escapeHtml(confidence.level)}">${escapeHtml(confidence.label)}</span></div><div class="mt-2 flex flex-wrap gap-2">${colourDetails.flowerColours.slice(0, 3).map(colour => `<span class="colour-chip colour-${escapeHtml(colour)}">${escapeHtml(colour)}</span>`).join('')}${colourDetails.foliageColours.slice(0, 2).map(colour => `<span class="colour-chip colour-${escapeHtml(colour)}">leaf: ${escapeHtml(colour)}</span>`).join('')}</div><p class="mt-4 text-sm leading-6 text-stone-600">${escapeHtml(description)}</p><a class="source-link" href="${escapeHtml(plant.source_url)}" target="_blank" rel="noopener">${sourceLinkLabel(plant)}</a></div>
    </article>`;
    }).join('') : noResultsMessage;
  }
   
  // Update pagination controls
  updatePagination(totalPages, visible.length);
  setColourChipGroupState('flowerColour');
  setColourChipGroupState('foliageColour');
  setColourChipGroupState('colourPattern');
  setReviewModeState(filters.reviewOnly);
  document.querySelectorAll('.category-tab').forEach(tab => { const active = tab.dataset.category === category; tab.classList.toggle('is-active', active); tab.setAttribute('aria-selected', String(active)); });
  document.querySelectorAll('.find-photo-button').forEach(button => button.addEventListener('click', async () => {
    const plant = plants.find(item => item.id === button.dataset.plantId); if (!plant) return;
    button.disabled = true; button.textContent = 'Searching...';
    try {
      const response = await fetch(`/api/dog-safe-plants/photo-suggestion?name=${encodeURIComponent(plant.name)}&scientific_name=${encodeURIComponent(plant.scientific_name)}`);
      const suggestion = await parseJsonResponse(response, 'Photo suggestion API');
      if (!response.ok) throw new Error(suggestion.error || 'Photo suggestion request failed.');
      const ranked = (suggestion.candidates || [suggestion]);
      const selected = await choosePhotoCandidate(plant, ranked);
      if (!selected) throw new Error('Photo not approved.');
      const saved = await fetch(`/api/dog-safe-plants/${encodeURIComponent(plant.id)}/photo`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ image_url: selected.image_url, image_source_url: selected.source_url }) });
      const result = await parseJsonResponse(saved, 'Saved photo API');
      if (!saved.ok) throw new Error(result.error || 'Photo save failed.');
      plant.image_url = result.image_url; plant.image_source_url = selected.source_url; imageBrokenIds.delete(plant.id); renderPlants();
    } catch (error) { if (error.message !== 'Photo not approved.') importStatusMessage(error.message); }
    finally { button.disabled = false; button.textContent = 'Find correct photo'; }
  }));
  grid.querySelectorAll('[data-search-correction]').forEach(button => {
    button.addEventListener('click', () => {
      const query = button.dataset.searchCorrection || '';
      const input = document.querySelector('#plant-search');
      if (!input) return;
      acceptSearchSuggestion(query);
      if (input.value !== query) {
        input.value = query;
        filters.search = query;
        currentPage = 1;
        renderPlants();
      }
    });
  });

  document.querySelectorAll('[data-favorite-id]').forEach(button => button.addEventListener('click', async (event) => {
    event.stopPropagation();
    const id = button.dataset.favoriteId;
    const isFavorite = favoriteIds.has(id);
    
    // Update server
    if (isFavorite) {
      await removeFavorite(id);
    } else {
      await addFavorite(id);
    }
    
    // Update local state
    if (isFavorite) {
      favoriteIds.delete(id);
    } else {
      favoriteIds.add(id);
    }
    
    button.classList.toggle('is-favorite', favoriteIds.has(id));
    button.setAttribute('aria-label', `${favoriteIds.has(id) ? 'Remove from' : 'Add to'} favourites`);
    renderPlants();
    if (plantView === 'favorites') renderFavorites();
  }));
  document.querySelectorAll('[data-plant-id]').forEach(card => card.addEventListener('click', event => { if (event.target.closest('a,button')) return; openPlantProfile(plants.find(plant => plant.id === card.dataset.plantId)); }));
  renderLibraryView();
  renderFavorites();
}

function formatSeasonalityInfo(seasonality) {
  if (!seasonality) return 'Information not available';
  if (seasonality.year_round === true) return 'Year-round';
  
  const monthNames = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  const peakMonths = (seasonality.peak_bloom_months || [])
    .map(m => monthNames[m - 1])
    .join(', ');
  if ((seasonality.peak_bloom_months || []).length >= 12) return 'Year-round';
  
  if (!peakMonths) return 'No specific bloom season data';
  return `Peak: ${peakMonths}`;
}

function toSentence(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  return text.charAt(0).toUpperCase() + text.slice(1);
}

function formatList(value, fallback = 'Not available') {
  if (Array.isArray(value)) {
    const cleaned = value.map(item => String(item || '').trim()).filter(Boolean);
    return cleaned.length ? cleaned.join(', ') : fallback;
  }
  const text = String(value || '').trim();
  return text || fallback;
}

function estimateGrowingTime(plant, guidance) {
  const details = `${String(plant?.description || '').toLowerCase()} ${String(plant?.growth_habit || '').toLowerCase()}`;
  const lifecycle = inferLifecycleDetails(plant);
  if (lifecycle.bucket === 'annual') {
    if (lifecycle.label === 'Hardy annual') return '8-12 weeks to bloom or usable display';
    if (lifecycle.label === 'Half-hardy annual') return '10-16 weeks from sowing to bloom';
    if (lifecycle.label === 'Tender annual') return '12-18 weeks from sowing to bloom';
    return 'Single growing season to bloom';
  }
  if (details.includes('annual')) return 'Single growing season (annual)';
  if (details.includes('perennial')) return 'Returns yearly after establishment (perennial)';
  if (details.includes('bulb') || String(plant?.name || '').toLowerCase().includes('amaryllis')) return '8-12 weeks to bloom from active growth';
  if (details.includes('shrub')) return '1-2 seasons to establish';
  if (details.includes('vine') || details.includes('climber')) return 'One season to establish, fuller growth from year 2';
  return guidance.typicalGrowingTime;
}

function formatMatureSize(plant, guidance) {
  const size = plant?.mature_size;
  if (size && typeof size === 'object') {
    const height = Number(size.height_cm);
    const spread = Number(size.spread_cm);
    if (Number.isFinite(height) || Number.isFinite(spread)) {
      const parts = [];
      if (Number.isFinite(height)) parts.push(`Height ${height} cm`);
      if (Number.isFinite(spread)) parts.push(`Spread ${spread} cm`);
      return parts.join(' · ');
    }
  }
  return guidance.matureSize;
}

function profileFact(label, value) {
  return `<div class="profile-fact"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value || 'Not available')}</dd></div>`;
}

function hasValue(value) {
  if (value === null || value === undefined) return false;
  if (Array.isArray(value)) return value.some(item => hasValue(item));
  if (typeof value === 'object') return Object.values(value).some(item => hasValue(item));
  return String(value).trim().length > 0;
}

function getProfileOverride(plant) {
  const base = profileOverrides?.[plant?.id] || {};
  const lifecycleData = lifecycleHardinessOverrides?.[plant?.id] || {};
  return { ...base, ...lifecycleData };
}

function getToxicityEvidenceForPlant(plant) {
  const record = toxicityEvidenceOverrides?.[plant?.id];
  if (!record || typeof record !== 'object') return null;
  const evidence = Array.isArray(record.evidence) ? record.evidence : [];
  return {
    name: record.name || plant?.name || 'Unknown plant',
    scientificName: record.scientific_name || plant?.scientific_name || '',
    currentStatus: record.safety_status_current || plant?.safety_status || 'Unknown',
    evidence,
    updatedAt: record._meta?.updated_at || null,
  };
}

function getPlantSynonyms(plant) {
  const record = plantSynonymOverrides?.[plant?.id];
  if (!record || typeof record !== 'object') return [];
  const aliases = Array.isArray(record.aliases) ? record.aliases : [];
  return [...new Set(aliases.map(item => String(item || '').trim()).filter(Boolean))];
}

function normaliseColourToken(token) {
  const value = String(token || '').toLowerCase().trim();
  if (!value) return '';
  if (value.includes('bicolor') || value.includes('bi-colour') || value.includes('bicolour')) return 'bicolour';
  if (value.includes('varieg')) return 'variegated';
  if (value.includes('purple') || value.includes('violet') || value.includes('lilac') || value.includes('lavender') || value.includes('mauve')) return 'purple';
  if (value.includes('pink') || value.includes('rose') || value.includes('magenta') || value.includes('fuchsia')) return 'pink';
  if (value.includes('red') || value.includes('scarlet') || value.includes('crimson') || value.includes('burgundy')) return 'red';
  if (value.includes('orange') || value.includes('coral') || value.includes('apricot')) return 'orange';
  if (value.includes('yellow') || value.includes('gold') || value.includes('amber')) return 'yellow';
  if (value.includes('blue') || value.includes('azure') || value.includes('cyan')) return 'blue';
  if (value.includes('white') || value.includes('cream') || value.includes('ivory')) return 'white';
  if (value.includes('green')) return 'green';
  if (value.includes('silver') || value.includes('grey') || value.includes('gray')) return 'silver';
  if (value.includes('black')) return 'black';
  return value;
}

function uniqColours(values) {
  return [...new Set((Array.isArray(values) ? values : [values]).map(normaliseColourToken).filter(Boolean))];
}

function getPlantColourProfile(plant) {
  const record = plantColourOverrides?.[plant?.id];
  if (record && typeof record === 'object') {
    return {
      flowerColours: uniqColours(record.flower_colours || record.colours || []),
      foliageColours: uniqColours(record.foliage_colours || []),
      galleryImages: Array.isArray(record.gallery_images) ? record.gallery_images : [],
    };
  }
  return {
    flowerColours: [],
    foliageColours: [],
    galleryImages: [],
  };
}

function inferPlantColours(plant) {
  const blob = `${String(plant?.name || '')} ${String(plant?.scientific_name || '')} ${String(plant?.description || '')} ${String(plant?.seasonal_interest || '')} ${String(plant?.foliage_type || '')}`.toLowerCase();
  const flower = [];
  const foliage = [];
  const push = (list, colour) => { if (!list.includes(colour)) list.push(colour); };
  const patterns = [
    ['yellow', /yellow|gold|amber/],
    ['orange', /orange|coral|apricot/],
    ['red', /red|scarlet|crimson|burgundy/],
    ['pink', /pink|rose|magenta|fuchsia/],
    ['purple', /purple|violet|lilac|lavender|mauve/],
    ['blue', /blue|azure|cyan|cerulean/],
    ['white', /white|cream|ivory/],
    ['green', /green/],
    ['silver', /silver|grey|gray/],
    ['bicolour', /bicolou?r|bi[- ]?colour|multicolour|multi[- ]?colou?r|variegat/],
  ];
  patterns.forEach(([label, regex]) => {
    if (regex.test(blob)) push(flower, label);
  });
  if (!flower.length && /flower|bloom|blooms|colour|color/.test(blob)) push(flower, 'mixed');
  if (/variegat/.test(blob)) push(foliage, 'variegated');
  if (/silver|grey|gray/.test(blob)) push(foliage, 'silver');
  if (/dark green|green foliage|evergreen/.test(blob)) push(foliage, 'green');
  if (/purple foliage|burgundy foliage|bronze foliage/.test(blob)) push(foliage, 'purple');
  return {
    flowerColours: flower,
    foliageColours: foliage,
  };
}

function getPlantColourDetails(plant) {
  const override = getPlantColourProfile(plant);
  const inferred = inferPlantColours(plant);
  const flowerColours = override.flowerColours.length ? override.flowerColours : inferred.flowerColours;
  const foliageColours = override.foliageColours.length ? override.foliageColours : inferred.foliageColours;
  const galleryImages = override.galleryImages;
  const summaryParts = [];
  if (flowerColours.length) summaryParts.push(`Flowers: ${flowerColours.join(', ')}`);
  if (foliageColours.length) summaryParts.push(`Foliage: ${foliageColours.join(', ')}`);
  return {
    flowerColours,
    foliageColours,
    galleryImages,
    summary: summaryParts.join(' · ') || 'Colours vary by cultivar',
  };
}

function normaliseColourValues(values) {
  return [...new Set((Array.isArray(values) ? values : [values]).map(item => String(item || '').toLowerCase().trim()).filter(Boolean))];
}

function colourMatchesAny(colourValues, selectedValues) {
  const selected = normaliseColourValues(selectedValues);
  if (!selected.length) return true;
  const list = normaliseColourValues(colourValues);
  if (!list.length) return false;
  const aliases = {
    purple: ['purple', 'violet', 'lilac', 'lavender', 'mauve'],
    pink: ['pink', 'rose', 'magenta', 'fuchsia'],
    red: ['red', 'scarlet', 'crimson', 'burgundy'],
    orange: ['orange', 'coral', 'apricot'],
    yellow: ['yellow', 'gold', 'amber'],
    blue: ['blue', 'azure', 'cyan', 'cerulean'],
    white: ['white', 'cream', 'ivory'],
    green: ['green'],
    silver: ['silver', 'grey', 'gray'],
  };
  return selected.some(filter => {
    const patterns = aliases[filter] || [filter];
    return list.some(colour => patterns.includes(colour));
  });
}

function colourPatternMatchesAny(plant, selectedValues) {
  const selected = normaliseColourValues(selectedValues);
  if (!selected.length) return true;
  const colourDetails = getPlantColourDetails(plant);
  const colours = normaliseColourValues([...(colourDetails.flowerColours || []), ...(colourDetails.foliageColours || [])]);
  if (!colours.length) return false;
  return selected.some(filter => {
    if (filter === 'mixed') return colours.length >= 2;
    if (filter === 'bicolour') return colours.includes('bicolour') || colours.length >= 2;
    if (filter === 'variegated') return colours.includes('variegated');
    return false;
  });
}

function colourSummaryText(values) {
  const selected = normaliseColourValues(values);
  return selected.length ? selected.join(', ') : '';
}

function hasCurationNeeds(plant) {
  const colourDetails = getPlantColourDetails(plant);
  const imageUrl = String(plant?.image_url || '').trim();
  const hasRealImage = !!imageUrl && !/placeholder|default|no-image|example\.com|aspca-logo-square\.png|\/image_0\.jpg|\/static\/plant-placeholder\.svg/i.test(imageUrl);
  const confidence = sourceConfidence(plant).level;
  const missingColourData = !(colourDetails.flowerColours.length || colourDetails.foliageColours.length);
  return !hasRealImage || confidence === 'low' || missingColourData;
}

function renderReviewQueueCard(plant) {
  const confidence = sourceConfidence(plant);
  const sourceName = String(plant?.source_name || 'Source');
  const sourceStatus = String(plant?.source_status || 'Staged for manual review.');
  const sourceUrl = String(plant?.source_url || '').trim();
  const sourceDomain = String(plant?.source_domain || '').trim();
  const sourceLabel = sourceDomain || sourceUrl || 'Review source';
  const safetyStatus = normaliseSafetyStatus(plant?.safety_status);
  const isRisky = safetyStatus === 'Toxic' || safetyStatus === 'May be Toxic';
  const safetyClass = safetyStatus === 'Toxic' ? 'safety-toxic' : safetyStatus === 'May be Toxic' ? 'safety-may-be-toxic' : '';
  const primaryActionText = isRisky ? 'Approve as toxic' : 'Approve';
  const auditHistory = Array.isArray(plant?.audit_history) ? plant.audit_history : [];
  const latestDecision = auditHistory.length ? auditHistory[auditHistory.length - 1] : {
    status: plant?.audit_status || 'pending',
    note: 'Awaiting curator decision',
    performed_at: null,
  };
  const latestStatus = String(latestDecision.status || 'pending').toLowerCase();
  const decisionLabel = latestStatus === 'approved' ? 'Approved' : latestStatus === 'rejected' ? 'Rejected' : latestStatus === 'review-only' ? 'Review-only' : 'Pending';
  const decisionClass = latestStatus === 'approved' ? 'bg-emerald-100 text-emerald-800' : latestStatus === 'rejected' ? 'bg-red-100 text-red-800' : latestStatus === 'review-only' ? 'bg-amber-100 text-amber-800' : 'bg-stone-100 text-stone-700';
  const decisionTimestamp = latestDecision.performed_at ? new Date(latestDecision.performed_at).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' }) : 'No decision yet';

  return `
    <article class="plant-card plant-review-card" data-plant-id="${escapeHtml(plant.id)}">
      <div class="plant-image-frame">
        <span class="plant-image-unavailable">Review queue entry</span>
      </div>
      <div class="p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-xl font-bold text-stone-900">${escapeHtml(plant.name)}</h3>
            <p class="scientific-name">${escapeHtml(plant.scientific_name)}</p>
          </div>
          <span class="safety-badge ${safetyClass}">${escapeHtml(safetyStatus)}</span>
        </div>
        <div class="mt-2 flex flex-wrap gap-2">
          <span class="source-confidence-badge source-confidence-${escapeHtml(confidence.level)}">${escapeHtml(confidence.label)}</span>
          <span class="plant-type-badge">Review queue</span>
          <span class="placement-badge">${escapeHtml(sourceName)}</span>
        </div>
        <p class="mt-3 text-sm leading-6 text-stone-600">${escapeHtml(sourceStatus)}</p>
        <p class="mt-2 text-xs text-stone-500">${escapeHtml(sourceLabel)}</p>
        ${sourceUrl ? `<a class="source-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">Open source reference</a>` : ''}
        <div class="mt-4 border-t border-stone-200 pt-3">
          <div class="mb-1 flex items-center justify-between gap-2 text-[10px] uppercase tracking-wide text-stone-500">
            <span class="inline-flex items-center rounded-full px-2 py-1 font-semibold ${decisionClass}">${decisionLabel}</span>
            <span>${escapeHtml(decisionTimestamp)}</span>
          </div>
          <p class="text-xs leading-5 text-stone-600">${escapeHtml(latestDecision.note || 'Awaiting curator decision')}</p>
        </div>
        <div class="mt-4 flex gap-2">
          <button type="button" class="inline-flex items-center rounded-full bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700" data-review-action="approve" data-plant-id="${escapeHtml(plant.id)}">${primaryActionText}</button>
          <button type="button" class="inline-flex items-center rounded-full border border-stone-300 bg-white px-3 py-1.5 text-xs font-semibold text-stone-700 transition hover:bg-stone-100" data-review-action="reject" data-plant-id="${escapeHtml(plant.id)}">Reject</button>
        </div>
      </div>
    </article>`;
}

function setColourChipGroupState(groupKey) {
  const selected = new Set(normaliseColourValues(filters[groupKey]));
  document.querySelectorAll(`[data-colour-group="${groupKey}"]`).forEach(button => {
    const value = String(button.dataset.colourValue || 'all').toLowerCase();
    const active = value === 'all' ? !selected.size : selected.has(value);
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function setReviewModeState(enabled) {
  const button = document.querySelector('#missing-plants-review');
  if (!button) return;
  button.classList.toggle('is-active', enabled);
  button.setAttribute('aria-pressed', String(enabled));
}

function confidenceIcon(level) {
  if (level === 'strong') return { icon: '🟢', label: 'strong data' };
  if (level === 'missing') return { icon: '🔴', label: 'missing' };
  return { icon: '🟠', label: 'inferred' };
}

function profileFactWithConfidence(label, fact) {
  const { icon, label: confidenceLabel } = confidenceIcon(fact.confidence);
  return `<div class="profile-fact profile-fact-${escapeHtml(fact.confidence)}"><dt>${escapeHtml(label)} <span class="profile-fact-confidence" title="${escapeHtml(confidenceLabel)}">${icon}</span></dt><dd>${escapeHtml(fact.value || 'Not available')}</dd></div>`;
}

function resolveProfileFact({ override, explicit, inferred }) {
  if (hasValue(override)) return { value: formatList(override), confidence: 'strong' };
  if (hasValue(explicit)) return { value: formatList(explicit), confidence: 'strong' };
  if (hasValue(inferred)) return { value: formatList(inferred), confidence: 'inferred' };
  return { value: 'Not available', confidence: 'missing' };
}

function inferBeginnerFriendliness(plant) {
  let score = 3;
  const textBlob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.care_notes || '').toLowerCase()} ${String(plant?.watering_needs || '').toLowerCase()}`;
  if (textBlob.includes('easy') || textBlob.includes('hardy') || textBlob.includes('low maintenance')) score += 1;
  if (textBlob.includes('drought')) score += 1;
  if (textBlob.includes('frequent') || textBlob.includes('high maintenance') || textBlob.includes('sensitive')) score -= 1;
  if (String(plant?.safety_status || '').toLowerCase() === 'toxic') score -= 1;
  score = Math.max(1, Math.min(5, score));
  const label = score >= 5 ? 'Very easy' : score >= 4 ? 'Easy' : score === 3 ? 'Moderate' : score === 2 ? 'Challenging' : 'Advanced';
  return `${score}/5 (${label})`;
}

function estimateFirstYield(plant, growingTime) {
  const category = String(plant?.category || '').toLowerCase();
  const lifecycle = inferLifecycleDetails(plant);
  if (lifecycle.bucket === 'annual') {
    if (category === 'vegetables') return '6-12 weeks to first harvest (annual crop)';
    if (lifecycle.label === 'Hardy annual') return '8-12 weeks to first bloom';
    return '10-18 weeks to first bloom or display';
  }
  if (category === 'vegetables') return '6-12 weeks to first harvest (variety dependent)';
  if (category === 'fruit') return 'First fruit in 3-12+ months (species dependent)';
  if (category === 'herbs') return '4-8 weeks to first cuttings';
  if (category === 'flowers') return `First blooms in about ${growingTime.toLowerCase()}`;
  if (category === 'grasses') return '1 growing season to establish form';
  return growingTime;
}

function inferWinterProtection(hardiness, plant) {
  const zone = String(hardiness || '').toUpperCase();
  const textBlob = `${String(plant?.name || '').toLowerCase()} ${String(plant?.scientific_name || '').toLowerCase()} ${String(plant?.description || '').toLowerCase()} ${String(plant?.indoor_outdoor || '').toLowerCase()}`;
  const tender = textBlob.includes('amaryllis') || textBlob.includes('hippeastrum') || textBlob.includes('indoor') || textBlob.includes('tropical');
  if (tender || zone.includes('H1') || zone.includes('H2') || zone.includes('H3')) {
    return { badge: 'Winter protection needed', note: 'Protect from frost, mulch root zone, or move containers indoors.', needsProtection: true };
  }
  return { badge: 'Winter hardy', note: 'Usually fine outdoors with normal seasonal care.', needsProtection: false };
}

function inferFoliageType(plant) {
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.growth_habit || '').toLowerCase()}`;
  if (blob.includes('evergreen')) return 'Evergreen';
  if (blob.includes('deciduous')) return 'Deciduous';
  return 'Semi-evergreen / variable by climate';
}

function inferSeasonalInterest(seasonInfo, plant) {
  const category = String(plant?.category || '').toLowerCase();
  if (seasonInfo && seasonInfo !== 'Information not available' && seasonInfo !== 'No specific bloom season data') return `${seasonInfo}; best ornamental display in active bloom months`;
  if (category === 'grasses') return 'Summer texture and autumn movement; winter structure if left standing';
  if (category === 'fruit') return 'Spring blossom and fruiting interest later in season';
  return 'Spring to late-season foliage and flower interest (variety dependent)';
}

function inferFragrance(plant) {
  const blob = `${String(plant?.name || '').toLowerCase()} ${String(plant?.description || '').toLowerCase()}`;
  if (blob.includes('lavender') || blob.includes('rosemary') || blob.includes('mint') || blob.includes('thyme') || blob.includes('jasmine') || blob.includes('scent')) return 'Aromatic foliage or scented flowers';
  return 'None to mild';
}

function inferPollinatorValue(plant) {
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.name || '').toLowerCase()} ${String(plant?.category || '').toLowerCase()}`;
  if (blob.includes('pollinator') || blob.includes('bee') || blob.includes('butterfly') || blob.includes('nectar')) return 'High';
  if (blob.includes('flower') || blob.includes('herb')) return 'Moderate';
  return 'Low to moderate';
}

function inferWildlifeResistance(plant) {
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.name || '').toLowerCase()}`;
  if (blob.includes('deer resistant') || blob.includes('rabbit resistant')) return 'Resistant';
  return 'Not specified';
}

function inferLifecycle(plant) {
  return inferLifecycleDetails(plant).label;
}

function inferLifecycleDetails(plant) {
  const category = String(plant?.category || '').toLowerCase();
  const blob = `${String(plant?.name || '').toLowerCase()} ${String(plant?.description || '').toLowerCase()} ${String(plant?.growth_habit || '').toLowerCase()} ${String(plant?.seasonal_interest || '').toLowerCase()} ${String(plant?.hardiness_zone || plant?.hardiness_zones_uk || '').toLowerCase()}`;
  const plantName = String(plant?.name || '').toLowerCase();
  const hardiness = String(plant?.hardiness_zone || plant?.hardiness_zones_uk || '').toUpperCase();
  const isAnnual = blob.includes('annual') || blob.includes('summer bedding') || blob.includes('seasonal colour');
  const isBiennial = blob.includes('biennial');
  const isShortLivedPerennial = blob.includes('short-lived perennial') || blob.includes('short lived perennial');
  const isBulb = blob.includes('bulb') || blob.includes('corm') || blob.includes('tuber') || blob.includes('amaryllis') || blob.includes('tulip') || blob.includes('dahlia');
  const isShrub = blob.includes('shrub') || blob.includes('woody') || ['fruit'].includes(category) && blob.includes('bush');
  let label = 'Perennial';
  if (isShortLivedPerennial) label = 'Short-lived perennial';
  else if (isBiennial) label = 'Biennial';
  else if (isAnnual) {
    const tenderHints = blob.includes('frost-tender') || blob.includes('half-hardy') || blob.includes('half hardy') || hardiness.includes('H1') || hardiness.includes('H2');
    const hardyHints = blob.includes('hardy annual') || blob.includes('self-seeding') || hardiness.includes('H3') || hardiness.includes('H4') || hardiness.includes('H5') || hardiness.includes('H6') || hardiness.includes('H7');
    if (tenderHints && !hardyHints) label = blob.includes('tender') || hardiness.includes('H1') ? 'Tender annual' : 'Half-hardy annual';
    else if (hardyHints && !tenderHints) label = 'Hardy annual';
    else label = 'Annual';
  } else if (isBulb) label = 'Bulb';
  else if (isShrub) label = 'Shrub';

  let tenderness = 'Hardy';
  if (label.includes('Tender') || hardiness.includes('H1') || hardiness.includes('H2')) tenderness = 'Frost-tender';
  else if (label.includes('Half-hardy') || hardiness.includes('H2')) tenderness = 'Half-hardy';
  else if (hardiness.includes('H3')) tenderness = 'Hardy';
  else if (hardiness.includes('H4') || hardiness.includes('H5') || hardiness.includes('H6') || hardiness.includes('H7')) tenderness = 'Hardy';
  if (label === 'Bulb' && blob.includes('indoors')) tenderness = 'Frost-tender';

  let sowingWindow = 'Spring or autumn (species dependent)';
  if (label === 'Hardy annual') sowingWindow = 'Direct sow spring to early summer; some also sow in autumn';
  else if (label === 'Half-hardy annual') sowingWindow = 'Start under cover in spring; plant out after last frost';
  else if (label === 'Tender annual') sowingWindow = 'Start under cover after frost risk passes; keep warm';
  else if (label === 'Biennial') sowingWindow = 'Sow in spring or summer for flowering next year';
  else if (label === 'Perennial') sowingWindow = 'Spring or autumn planting';

  let deadheadingNeeded = 'Not usually';
  if (category === 'flowers' || blob.includes('flower') || label.includes('annual')) {
    deadheadingNeeded = blob.includes('repeat bloom') || blob.includes('deadhead') ? 'Yes' : 'Often beneficial';
  }
  if (category === 'vegetables' || category === 'herbs') {
    deadheadingNeeded = blob.includes('flower') ? 'Usually not needed' : 'Not usually';
  }

  let selfSeedingRisk = 'Low';
  if (blob.includes('self-seeding') || blob.includes('self seeding') || blob.includes('naturalise') || blob.includes('seed freely')) selfSeedingRisk = 'Moderate to high';
  else if (label.includes('Annual') && (blob.includes('cottage garden') || blob.includes('open pollinated'))) selfSeedingRisk = 'Moderate';

  let containerSuitability = 'Good';
  if (blob.includes('container') || blob.includes('pot')) containerSuitability = 'Excellent';
  else if (label.includes('Tender') || label.includes('Half-hardy')) containerSuitability = 'Excellent for seasonal display';
  else if (label === 'Shrub' || label === 'Perennial') containerSuitability = 'Possible with adequate pot size';

  let winterHandling = 'Overwinter outdoors if hardy; protect in severe frost.';
  if (label === 'Hardy annual') winterHandling = 'Sow afresh each year; most plants finish before frost.';
  else if (label === 'Half-hardy annual') winterHandling = 'Treat as seasonal bedding; replant after frost risk or overwinter indoors if potted.';
  else if (label === 'Tender annual') winterHandling = 'Keep frost-free; overwinter indoors only if potted, otherwise resow.';
  else if (label === 'Biennial') winterHandling = 'Usually survives one winter, flowers the second season, then declines.';
  else if (label === 'Short-lived perennial') winterHandling = 'May return for a few seasons, but often declines after 2-3 years.';
  else if (label === 'Bulb') winterHandling = blob.includes('hardy') ? 'Can remain in the ground if free-draining; lift/store if tender.' : 'Often lifted or protected in winter, depending on species.';

  return {
    label,
    bucket: label.includes('annual') ? 'annual' : label === 'Biennial' ? 'biennial' : label === 'Bulb' ? 'bulb' : label === 'Shrub' ? 'shrub' : label === 'Short-lived perennial' ? 'short-lived perennial' : 'perennial',
    tenderness,
    sowingWindow,
    deadheadingNeeded,
    selfSeedingRisk,
    containerSuitability,
    winterHandling,
  };
}

function inferPropagation(plant) {
  const category = String(plant?.category || '').toLowerCase();
  if (category === 'grasses') return 'Division or seed';
  if (category === 'herbs') return 'Cuttings, seed, or division';
  if (category === 'fruit') return 'Cuttings, grafting, or runners (species dependent)';
  if (category === 'vegetables') return 'Mostly from seed';
  return 'Seed, cuttings, or division (species dependent)';
}

function inferPestsAndDisease(plant) {
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.name || '').toLowerCase()}`;
  if (blob.includes('rose')) return 'Watch for aphids, black spot, and powdery mildew';
  if (blob.includes('mint')) return 'Can spread aggressively; watch for rust and mildew';
  if (blob.includes('lily') || blob.includes('amaryllis')) return 'Protect bulbs from rot in poorly drained soil';
  return 'Monitor for aphids, slugs/snails, and fungal leaf spots';
}

function inferCompanionNote(plant) {
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.name || '').toLowerCase()} ${String(plant?.category || '').toLowerCase()}`;
  if (blob.includes('mint')) return 'Can spread aggressively—plant with root barrier or in containers.';
  if (blob.includes('grasses') || blob.includes('grass')) return 'Place where mature clump size has room; divide if overcrowded.';
  if (blob.includes('vine') || blob.includes('climber')) return 'Needs support and can shade neighbors if not pruned.';
  return 'Generally compatible when spaced by mature spread and grouped by water needs.';
}

function matchesLifecycleFilter(plant, filterValue) {
  const value = String(filterValue || 'all').toLowerCase();
  if (value === 'all') return true;
  const lifecycle = inferLifecycleDetails(plant);
  const bucket = lifecycle.bucket;
  const label = lifecycle.label.toLowerCase();
  if (value === 'annual') return bucket === 'annual';
  if (value === 'biennial') return bucket === 'biennial';
  if (value === 'perennial') return bucket === 'perennial';
  if (value === 'short-lived-perennial') return bucket === 'short-lived perennial';
  if (value === 'bulb') return bucket === 'bulb';
  if (value === 'shrub') return bucket === 'shrub';
  if (value === 'hardy-annual') return label === 'hardy annual';
  if (value === 'half-hardy-annual') return label === 'half-hardy annual';
  if (value === 'tender-annual') return label === 'tender annual';
  return true;
}

function parseSizeToCm(text) {
  const value = String(text || '').toLowerCase();
  if (!value.trim()) return null;
  const cmMatches = [...value.matchAll(/(\d+(?:\.\d+)?)\s*cm\b/g)].map(match => Number(match[1])).filter(Number.isFinite);
  const mMatches = [...value.matchAll(/(\d+(?:\.\d+)?)\s*m\b/g)].map(match => Number(match[1]) * 100).filter(Number.isFinite);
  const ftMatches = [...value.matchAll(/(\d+(?:\.\d+)?)\s*(?:ft|feet|foot)\b/g)].map(match => Number(match[1]) * 30.48).filter(Number.isFinite);
  const inMatches = [...value.matchAll(/(\d+(?:\.\d+)?)\s*(?:in|inch|inches)\b/g)].map(match => Number(match[1]) * 2.54).filter(Number.isFinite);
  const numbers = [...cmMatches, ...mMatches, ...ftMatches, ...inMatches];
  if (!numbers.length) return null;
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  return { minCm: min, maxCm: max };
}

function matureSizeTextForPlant(plant) {
  const guidance = growingGuidance[plant?.category] || growingGuidance.flowers;
  return formatMatureSize(plant, guidance);
}

function matchesRangeFilter(size, filterValue) {
  const value = String(filterValue || 'all').toLowerCase();
  if (value === 'all' || !size) return true;
  const min = Number(size.minCm);
  const max = Number(size.maxCm);
  if (value === 'compact') return Number.isFinite(min) && min < 30;
  if (value === 'small') return Number.isFinite(max) && max >= 30 && Number.isFinite(min) && min < 90;
  if (value === 'medium') return Number.isFinite(max) && max >= 90 && Number.isFinite(min) && min < 180;
  if (value === 'large') return Number.isFinite(max) && max >= 180;
  return true;
}

function matchesTextFilter(value, filterValue) {
  const filter = String(filterValue || 'all').toLowerCase();
  if (filter === 'all') return true;
  const text = String(value || '').toLowerCase();
  if (!text) return false;
  return text.includes(filter);
}

function matchesContainerFilter(value, filterValue) {
  const filter = String(filterValue || 'all').toLowerCase();
  if (filter === 'all') return true;
  const text = String(value || '').toLowerCase();
  if (!text) return false;
  if (filter === 'excellent') return text.includes('excellent');
  if (filter === 'very good') return text.includes('very good');
  if (filter === 'possible') return text.includes('possible') || text.includes('good') || text.includes('very good') || text.includes('excellent');
  return true;
}

function matchesTraitFilter(value, filterValue, patternsByFilter) {
  const filter = String(filterValue || 'all').toLowerCase();
  if (filter === 'all') return true;
  const text = String(value || '').toLowerCase();
  if (!text) return false;
  const patterns = patternsByFilter[filter] || [filter];
  return patterns.some(pattern => text.includes(pattern));
}

function inferPetSafetyDetail(plant) {
  const safety = String(plant?.safety_status || '');
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.name || '').toLowerCase()} ${String(plant?.category || '').toLowerCase()}`;
  if (safety === 'Toxic') return 'Toxic if ingested. Keep out of pet reach.';
  if (blob.includes('grass') || blob.includes('sharp') || blob.includes('blade')) return 'Non-toxic, but coarse or sharp leaves may cause mild mechanical irritation if chewed heavily.';
  return 'Non-toxic status based on current source data; still discourage heavy chewing.';
}

function inferGardenLayer(plant, matureSizeText) {
  const heightMatch = /height\s+(\d+)\s*cm/i.exec(String(matureSizeText || ''));
  const height = heightMatch ? Number(heightMatch[1]) : NaN;
  const blob = `${String(plant?.description || '').toLowerCase()} ${String(plant?.growth_habit || '').toLowerCase()}`;
  if (Number.isFinite(height)) {
    if (height < 35) return 'Foreground / edging';
    if (height <= 90) return 'Mid-border';
    return 'Backdrop / tall structure';
  }
  if (blob.includes('trailing') || blob.includes('container')) return 'Container / edge spillover';
  return 'Mid-border (adjust after observing mature growth)';
}

function openPlantProfile(plant) {
  if (!plant) return;
  const guidance = growingGuidance[plant.category] || growingGuidance.flowers;
  const override = getProfileOverride(plant);
  const seasonInfo = formatSeasonalityInfo(plant.seasonality);
  const confidence = sourceConfidence(plant);
  const sunlightFact = resolveProfileFact({ override: override.sun_exposure, explicit: plant.sun_exposure, inferred: guidance.sunExposure });
  const wateringFact = resolveProfileFact({ override: override.watering_needs, explicit: plant.watering_needs, inferred: guidance.watering });
  const soilFact = resolveProfileFact({ override: override.soil_type, explicit: plant.soil_preference, inferred: guidance.soil });
  const hardinessFact = resolveProfileFact({ override: override.hardiness_zone, explicit: (plant.hardiness_zone || plant.hardiness_zones_uk), inferred: 'RHS H4' });
  const placement = getPlantPlacementTags(plant).join(' / ');
  const lifecycleDetails = inferLifecycleDetails(plant);
  const growingTimeFact = resolveProfileFact({ override: override.typical_growing_time, explicit: plant.typical_growing_time, inferred: estimateGrowingTime(plant, guidance) });
  const timeToFirstFact = resolveProfileFact({ override: override.time_to_first_yield, explicit: plant.time_to_first_yield, inferred: estimateFirstYield(plant, growingTimeFact.value) });
  const matureSizeFact = resolveProfileFact({ override: override.mature_size, explicit: formatMatureSize(plant, guidance), inferred: guidance.matureSize });
  const confidenceLabel = confidence.label.replace('Source: ', '');
  const sourceType = toSentence(plant.source_type || 'unclassified');
  const growthHabitFact = resolveProfileFact({ override: override.growth_habit, explicit: plant.growth_habit, inferred: 'Upright' });
  const lifecycleSummary = lifecycleDetails.bucket === 'annual'
    ? 'Annual'
    : lifecycleDetails.bucket === 'short-lived perennial'
      ? 'Short-lived perennial'
      : lifecycleDetails.bucket === 'biennial'
        ? 'Biennial'
        : lifecycleDetails.bucket === 'bulb'
          ? 'Bulb'
          : lifecycleDetails.bucket === 'shrub'
            ? 'Shrub'
            : 'Perennial';
  const lifecycleFact = resolveProfileFact({ override: override.lifecycle, explicit: plant.lifecycle, inferred: lifecycleSummary });
  const lifecycleSubtypeFact = resolveProfileFact({ override: override.lifecycle_subtype, explicit: plant.lifecycle_subtype, inferred: lifecycleDetails.label });
  const tendernessFact = resolveProfileFact({ override: override.tenderness, explicit: plant.tenderness, inferred: lifecycleDetails.tenderness });
  const sowingWindowFact = resolveProfileFact({ override: override.sowing_window, explicit: plant.sowing_window, inferred: lifecycleDetails.sowingWindow });
  const deadheadingFact = resolveProfileFact({ override: override.deadheading_needed, explicit: plant.deadheading_needed, inferred: lifecycleDetails.deadheadingNeeded });
  const selfSeedingFact = resolveProfileFact({ override: override.self_seeding_risk, explicit: plant.self_seeding_risk, inferred: lifecycleDetails.selfSeedingRisk });
  const containerSuitabilityFact = resolveProfileFact({ override: override.container_suitability, explicit: plant.container_suitability, inferred: lifecycleDetails.containerSuitability });
  const winterHandlingFact = resolveProfileFact({ override: override.winter_handling, explicit: plant.winter_handling, inferred: lifecycleDetails.winterHandling });
  const careTip = String(plant.care_notes || '').trim() || guidance.gardenNote;
  const wateringDate = String(care[plant.id]?.watering || '');
  const descriptionText = getPlantDescription(plant);
  const statusClass = plant.safety_status === 'Toxic' ? 'safety-toxic' : plant.safety_status === 'May be Toxic' ? 'safety-may-be-toxic' : '';
  const beginnerScore = inferBeginnerFriendliness(plant);
  const winter = inferWinterProtection(hardinessFact.value, plant);
  const winterBadgeClass = winter.needsProtection ? 'profile-badge-winter-alert' : 'profile-badge-winter-ok';
  const bloomFact = resolveProfileFact({ override: override.blooming_period, explicit: seasonInfo, inferred: 'Varies by cultivar' });
  const foliageFact = resolveProfileFact({ override: override.foliage_type, explicit: plant.foliage_type, inferred: inferFoliageType(plant) });
  const seasonalInterestFact = resolveProfileFact({ override: override.seasonal_interest, explicit: plant.seasonal_interest, inferred: inferSeasonalInterest(seasonInfo, plant) });
  const fragranceFact = resolveProfileFact({ override: override.fragrance, explicit: plant.fragrance, inferred: inferFragrance(plant) });
  const pollinatorFact = resolveProfileFact({ override: override.pollinator_value, explicit: plant.pollinator_value, inferred: inferPollinatorValue(plant) });
  const wildlifeFact = resolveProfileFact({ override: override.deer_rabbit_resistance, explicit: plant.deer_rabbit_resistance, inferred: inferWildlifeResistance(plant) });
  const propagationFact = resolveProfileFact({ override: override.propagation_method, explicit: plant.propagation_method, inferred: inferPropagation(plant) });
  const pestsFact = resolveProfileFact({ override: override.common_pests_diseases, explicit: plant.common_pests_diseases, inferred: inferPestsAndDisease(plant) });
  const companionFact = resolveProfileFact({ override: override.companion_compatibility, explicit: plant.companion_compatibility, inferred: inferCompanionNote(plant) });
  const petSafetyFact = resolveProfileFact({ override: override.pet_safety_detail, explicit: plant.pet_safety_detail, inferred: inferPetSafetyDetail(plant) });
  const layerFact = resolveProfileFact({ override: override.garden_layer, explicit: plant.garden_layer, inferred: inferGardenLayer(plant, matureSizeFact.value) });
  const synonymAliases = getPlantSynonyms(plant);
  const colourDetails = getPlantColourDetails(plant);
  const galleryItems = plantGalleryItems(plant);
  const heroPhoto = galleryItems[0] || null;
  const extraPhotos = galleryItems.slice(1);
  const bestUseTags = Array.isArray(override.best_use_tags) && override.best_use_tags.length
    ? override.best_use_tags
    : [pollinatorFact.value.includes('High') ? 'pollinator border' : '', layerFact.value.includes('Container') ? 'container' : '', String(plant.category || '').toLowerCase() === 'vegetables' ? 'edible patch' : '', wateringFact.value.toLowerCase().includes('dry') || wateringFact.value.toLowerCase().includes('drought') ? 'low-water bed' : '']
      .filter(Boolean);
  const riskAlerts = [];
  if (companionFact.value.toLowerCase().includes('aggressive') || companionFact.value.toLowerCase().includes('spread')) riskAlerts.push('Spreader risk: use spacing or barriers.');
  if (winter.needsProtection) riskAlerts.push('Frost risk: protect or move before hard frosts.');
  if (wateringFact.value.toLowerCase().includes('moist') || wateringFact.value.toLowerCase().includes('evenly')) riskAlerts.push('Overwatering risk: check topsoil moisture before watering.');
  if (!riskAlerts.length) riskAlerts.push('No major risk flags detected from current profile data.');
  const toxicityEvidence = getToxicityEvidenceForPlant(plant);
  const toxicityEvidenceSection = toxicityEvidence ? `
    <div class="profile-section-title">Toxicity evidence</div>
    <p class="text-sm text-stone-600">Current status: <strong>${escapeHtml(toxicityEvidence.currentStatus)}</strong></p>
    <details class="profile-evidence-panel">
      <summary>${escapeHtml(String(toxicityEvidence.evidence.length))} evidence record${toxicityEvidence.evidence.length === 1 ? '' : 's'}</summary>
      <ul class="profile-evidence-list">
        ${toxicityEvidence.evidence.slice(0, 6).map(item => `
          <li>
            <div class="profile-evidence-meta">
              <span>${escapeHtml(item.source_name || 'Source')}</span>
              <span>${escapeHtml(String(item.dog_severity || 'unknown'))}</span>
              <span>${escapeHtml(String(item.confidence || 'unknown'))}</span>
            </div>
            <p>${escapeHtml(item.quote || 'No quote captured.')}</p>
            ${item.source_url ? `<a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">Open source</a>` : ''}
          </li>
        `).join('')}
      </ul>
      ${toxicityEvidence.updatedAt ? `<p class="text-xs text-stone-500">Updated ${escapeHtml(toxicityEvidence.updatedAt)}</p>` : ''}
    </details>
  ` : '';
  const taskTimeline = override.task_timeline || (lifecycleDetails.bucket === 'annual' ? {
    Jan: ['Plan varieties and sowing dates', 'Check seed stock'],
    Feb: ['Start tender annuals under cover', 'Prepare trays and labels'],
    Mar: ['Sow hardy annuals and thin seedlings', 'Harden off where needed'],
    Apr: ['Plant out after frost risk', 'Feed lightly and water regularly'],
    May: ['Continue succession sowing', 'Deadhead where flowering starts'],
    Jun: ['Water in dry spells', 'Support taller stems if needed'],
    Jul: ['Deadhead to prolong display', 'Monitor for pests'],
    Aug: ['Keep deadheading or harvest seed', 'Replace tired displays'],
    Sep: ['Collect seed from selected plants', 'Clear spent annuals as they finish'],
    Oct: ['Remove frost-tender displays', 'Compost spent plants'],
    Nov: ['Store seed dry and cool', 'Plan next season'],
    Dec: ['Review success and choose next annuals', 'Minimal watering for any overwintered pots'],
  } : {
    Jan: ['Inspect for frost damage', 'Check drainage and avoid waterlogging'],
    Feb: ['Prepare pruning tools', 'Plan feed schedule'],
    Mar: ['Light prune and tidy', 'Top-dress with compost'],
    Apr: ['Increase watering as growth starts', 'Watch for aphids and slugs'],
    May: ['Feed during active growth', 'Mulch to retain moisture'],
    Jun: ['Deadhead blooms', 'Monitor heat and moisture'],
    Jul: ['Deep water in dry spells', 'Inspect pests weekly'],
    Aug: ['Trim lightly to shape', 'Maintain mulch cover'],
    Sep: ['Reduce feed frequency', 'Check mature spacing'],
    Oct: ['Prepare winter protection', 'Remove diseased foliage'],
    Nov: ['Protect tender growth', 'Water sparingly'],
    Dec: ['Minimal watering', 'Inspect supports and labels'],
  });
  
  document.querySelector('#plant-profile-content').innerHTML = `
    <p class="plant-eyebrow text-emerald-700">Plant profile</p>
    <h2 id="plant-profile-title" class="mt-1 text-3xl font-bold">${escapeHtml(plant.name)}</h2>
    <p class="scientific-name">${escapeHtml(plant.scientific_name)}</p>
    ${heroPhoto ? `
      <div class="plant-profile-hero">
        <a class="plant-profile-hero-link" href="${escapeHtml(heroPhoto.source_url || plant.source_url || '#')}" target="_blank" rel="noopener">
          <img src="${escapeHtml(heroPhoto.image_url)}" alt="${escapeHtml(heroPhoto.label || plant.name)}" loading="eager">
        </a>
        <div class="plant-profile-hero-meta">
          <span>${escapeHtml(heroPhoto.label || 'Main photo')}</span>
          ${heroPhoto.source_url ? `<a href="${escapeHtml(heroPhoto.source_url)}" target="_blank" rel="noopener">${escapeHtml(heroPhoto.source_name || 'Open source')}</a>` : ''}
        </div>
      </div>
    ` : ''}
    <div class="profile-chip-row">
      <span class="profile-chip">${escapeHtml(toSentence(plant.category))}</span>
      <span class="profile-chip">${escapeHtml(placement)}</span>
      <span class="profile-chip">${escapeHtml(lifecycleDetails.label)}</span>
      <span class="profile-chip">${escapeHtml(beginnerScore)} beginner score</span>
      <span class="profile-chip">${escapeHtml(confidenceLabel)} confidence</span>
      <span class="profile-chip ${winterBadgeClass}">${escapeHtml(winter.badge)}</span>
      <span class="safety-badge ${statusClass}">${escapeHtml(plant.safety_status)}</span>
    </div>
    <p class="mt-4 text-stone-600">${escapeHtml(descriptionText)}</p>
    ${plant.source_status ? `<p class="profile-warning">${escapeHtml(plant.source_status)}</p>` : ''}
    <div class="profile-section-title">Growing profile</div>
    <dl class="profile-facts profile-facts-grid">
      ${profileFactWithConfidence('Typical growing time', growingTimeFact)}
      ${profileFactWithConfidence('Time to first flowers/harvest', timeToFirstFact)}
      ${profileFactWithConfidence('Growth habit', growthHabitFact)}
      ${profileFactWithConfidence('Blooming period', bloomFact)}
      ${profileFactWithConfidence('Mature size', matureSizeFact)}
      ${profileFactWithConfidence('Sun exposure', sunlightFact)}
      ${profileFactWithConfidence('Soil type', soilFact)}
      ${profileFactWithConfidence('Watering needs', wateringFact)}
      ${profileFactWithConfidence('Hardiness zone', hardinessFact)}
      ${profileFactWithConfidence('Lifecycle', lifecycleFact)}
      ${profileFactWithConfidence('Lifecycle subtype', lifecycleSubtypeFact)}
      ${profileFactWithConfidence('Tenderness', tendernessFact)}
      ${profileFactWithConfidence('Sowing / planting window', sowingWindowFact)}
      ${profileFactWithConfidence('Deadheading needed', deadheadingFact)}
      ${profileFactWithConfidence('Self-seeding risk', selfSeedingFact)}
      ${profileFactWithConfidence('Container suitability', containerSuitabilityFact)}
      ${profileFactWithConfidence('Winter handling', winterHandlingFact)}
      ${profileFactWithConfidence('Winter protection', { value: winter.note, confidence: winter.needsProtection ? 'inferred' : 'strong' })}
      ${profileFactWithConfidence('Foliage type', foliageFact)}
      ${profileFactWithConfidence('Seasonal interest', seasonalInterestFact)}
      ${profileFactWithConfidence('Fragrance', fragranceFact)}
      ${profileFactWithConfidence('Pollinator value', pollinatorFact)}
      ${profileFactWithConfidence('Deer/rabbit resistance', wildlifeFact)}
      ${profileFactWithConfidence('Lifecycle overview', lifecycleFact)}
      ${profileFactWithConfidence('Propagation method', propagationFact)}
      ${profileFactWithConfidence('Common pests & diseases', pestsFact)}
      ${profileFactWithConfidence('Garden layer', layerFact)}
      ${profileFactWithConfidence('Companion planting compatibility', companionFact)}
      ${profileFactWithConfidence('Pet safety detail', petSafetyFact)}
      ${profileFactWithConfidence('Source type', { value: sourceType, confidence: 'strong' })}
      ${profileFactWithConfidence('Source confidence', { value: confidenceLabel, confidence: 'strong' })}
    </dl>
    ${toxicityEvidenceSection}
    <div class="profile-section-title">Best use tags</div>
    <div class="profile-chip-row">${bestUseTags.map(tag => `<span class="profile-chip">${escapeHtml(tag)}</span>`).join('')}</div>
    <div class="profile-section-title">Colours</div>
    <p class="text-sm text-stone-600">${escapeHtml(colourDetails.summary)}</p>
    <div class="profile-chip-row">
      ${(colourDetails.flowerColours.length ? colourDetails.flowerColours : ['mixed']).map(colour => `<span class="profile-chip profile-colour-chip profile-colour-${escapeHtml(colour)}">${escapeHtml(colour)}</span>`).join('')}
      ${colourDetails.foliageColours.length ? colourDetails.foliageColours.map(colour => `<span class="profile-chip profile-colour-chip profile-colour-${escapeHtml(colour)}">foliage: ${escapeHtml(colour)}</span>`).join('') : ''}
    </div>
    ${synonymAliases.length ? `
      <div class="profile-section-title">Common aliases</div>
      <div class="profile-chip-row">${synonymAliases.map(alias => `<span class="profile-chip">${escapeHtml(alias)}</span>`).join('')}</div>
    ` : ''}
    ${extraPhotos.length ? `
      <div class="profile-section-title">Image variants</div>
      <div class="plant-gallery-grid">
        ${extraPhotos.map(item => `
          <a class="plant-gallery-item" href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">
            <img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.label)}" loading="lazy">
            <span>${escapeHtml(item.label)}</span>
          </a>
        `).join('')}
      </div>
    ` : ''}
    <div class="profile-section-title">Risk alerts</div>
    <ul class="profile-alert-list">${riskAlerts.map(item => `<li>${escapeHtml(item)}</li>`).join('')}</ul>
    <div class="profile-section-title">Month-by-month task timeline</div>
    <div class="profile-timeline-grid">
      ${Object.entries(taskTimeline).map(([month, tasks]) => `<div class="profile-timeline-card"><p class="profile-timeline-month">${escapeHtml(month)}</p><ul>${(Array.isArray(tasks) ? tasks : [tasks]).map(task => `<li>${escapeHtml(task)}</li>`).join('')}</ul></div>`).join('')}
    </div>
    <p class="profile-warning">${escapeHtml(careTip)}</p>
    <label class="care-date">Next watering <input id="profile-watering-date" type="date" value="${escapeHtml(wateringDate)}"></label>
    <div class="mt-4 flex gap-2">
      <button id="add-to-library-btn" class="rounded-lg bg-emerald-700 px-4 py-2 font-bold text-white">Add to my garden</button>
      <a class="source-link" href="${escapeHtml(plant.source_url)}" target="_blank" rel="noopener">${sourceLinkLabel(plant)}</a>
    </div>
  `;
  document.querySelector('#plant-profile-modal').classList.remove('hidden');
  
  document.querySelector('#profile-watering-date').addEventListener('change', event => {
    care[plant.id] = { ...(care[plant.id] || {}), watering: event.target.value };
    renderLibraryView();
    syncLibrary();
  });
  
  document.querySelector('#add-to-library-btn').addEventListener('click', async () => {
    const locationName = await askPrompt('Where will you plant this? (e.g., "Patio pot", "Front garden")', '', 'Add to my garden');
    if (locationName === null) return;
    
    const result = await addUserPlant(plant.id, plant.name, locationName);
    if (result) {
      await showAlert(`${plant.name} added to your garden!`, 'Plant added');
      await loadUserPlants();
      // Create a default watering task
      await createCareTask(result.id, 'watering', 7);
      if (plantView === 'library') renderLibraryView();
    } else {
      await showAlert('Failed to add plant', 'Could not add plant');
    }
  });
}

function renderLibrary() { const list = document.querySelector('#plant-library-list'); const library = plants.filter(plant => favoriteIds.has(plant.id)); document.querySelector('#library-status').textContent = `${library.length} favourite plant${library.length === 1 ? '' : 's'} in the shared admin library.`; list.innerHTML = library.length ? library.map(plant => `<div class="library-item"><div><strong>${escapeHtml(plant.name)}</strong><br><span class="text-sm text-stone-500">${escapeHtml(plant.category)} · ${care[plant.id]?.watering ? `Water next ${escapeHtml(care[plant.id].watering)}` : 'No watering date set'}</span></div><button type="button" class="library-button" data-profile-id="${escapeHtml(plant.id)}">Profile</button></div>`).join('') : '<p class="text-sm text-stone-500">Use the star on a plant card to add it.</p>'; list.querySelectorAll('[data-profile-id]').forEach(button => button.addEventListener('click', () => openPlantProfile(plants.find(plant => plant.id === button.dataset.profileId)))); const watering = document.querySelector('#watering-list'); const dated = library.filter(plant => care[plant.id]?.watering).sort((a,b) => care[a.id].watering.localeCompare(care[b.id].watering)); watering.innerHTML = dated.length ? dated.map(plant => `<div class="library-item"><span><strong>${escapeHtml(plant.name)}</strong><br><span class="text-sm text-stone-500">${escapeHtml(care[plant.id].watering)}</span></span><span class="care-state">${care[plant.id].watering < new Date().toISOString().slice(0,10) ? 'Due' : 'Upcoming'}</span></div>`).join('') : '<p class="text-sm text-stone-500">No watering dates set.</p>'; }

function renderFavorites() {
  const list = document.querySelector('#plant-favorites-list');
  const favorites = plants.filter(plant => favoriteIds.has(plant.id));
  document.querySelector('#favorites-status').textContent = `${favorites.length} starred plant${favorites.length === 1 ? '' : 's'} in your quick reference.`;
  list.innerHTML = favorites.length ? favorites.map(plant => {
    const image = imageSources(plant)[0];
    return `<article class="plant-card" data-plant-id="${escapeHtml(plant.id)}">
      <div class="plant-image-frame">${image ? `<img src="${escapeHtml(image)}" alt="${escapeHtml(plant.name)}" loading="lazy" onload="plantImageLoaded(this);" onerror="this.onerror=null;this.hidden=true;this.nextElementSibling.hidden=false;">` : ''}<span class="plant-image-unavailable"${image ? ' hidden' : ''}>Verified photo unavailable</span></div>
      <div class="p-5"><div><h3 class="font-bold text-stone-900">${escapeHtml(plant.name)}</h3><p class="scientific-name text-sm">${escapeHtml(plant.scientific_name)}</p></div><p class="mt-2 text-xs text-stone-500">${escapeHtml(plant.category)} · ${escapeHtml(plant.safety_status)}</p><button type="button" class="mt-3 remove-fav-button rounded-lg bg-red-100 px-3 py-1 text-sm font-bold text-red-700" data-remove-id="${escapeHtml(plant.id)}">Remove from favorites</button></div>
    </article>`;
  }).join('') : '<p class="text-stone-500">No starred plants yet. Use the star on any plant to add it to your quick reference.</p>';
  list.querySelectorAll('.remove-fav-button').forEach(btn => btn.addEventListener('click', async (e) => {
    e.stopPropagation();
    const id = btn.dataset.removeId;
    await removeFavorite(id);
    favoriteIds.delete(id);
    renderFavorites();
    renderPlants();
  }));
  list.querySelectorAll('[data-plant-id]').forEach(card => card.addEventListener('click', event => {
    if (event.target.closest('button')) return;
    openPlantProfile(plants.find(plant => plant.id === card.dataset.plantId));
  }));
}

function setPlantDisplayMode(mode) {
  plantDisplayMode = mode === 'list' ? 'list' : 'cards';
  localStorage.setItem('plantDisplayMode', plantDisplayMode);
  document.querySelector('#plant-view-cards')?.classList.toggle('is-active', plantDisplayMode === 'cards');
  document.querySelector('#plant-view-list')?.classList.toggle('is-active', plantDisplayMode === 'list');
  renderPlants();
}

function catalogueExportRows(items) {
  return items.map(plant => ({
    id: plant.id,
    name: plant.name,
    scientific_name: plant.scientific_name,
    category: plant.category,
    safety_status: plant.safety_status,
    dog_toxicity_level: plant.safety_status === 'Toxic' ? 'TOXIC' : (plant.safety_status === 'May be Toxic' ? 'RISKY' : 'NON-TOXIC'),
    indoor_outdoor: getPlantPlacementTags(plant).join('|'),
    source_type: plant.source_type || '',
    source_confidence: sourceConfidence(plant).label.replace('Source: ', '').toLowerCase(),
    hardiness_zone: plant.hardiness_zone || '',
    source_url: plant.source_url || '',
  }));
}

function libraryExportRows() {
  return userPlants.map(entry => ({
    user_plant_id: entry.id,
    plant_id: entry.plant_id,
    plant_name: entry.plant_name,
    location_name: entry.location_name || '',
    location_zone: entry.location_zone || '',
    date_planted: entry.date_planted || '',
    quantity_planted: entry.quantity_planted || '',
    health_status: entry.health_status || 'good',
    indoor_outdoor: (() => {
      const plant = plants.find(item => String(item.id) === String(entry.plant_id));
      return plant ? getPlantPlacementTags(plant).join('|') : '';
    })(),
    safety_status: (() => {
      const plant = plants.find(item => String(item.id) === String(entry.plant_id));
      return plant?.safety_status || '';
    })(),
    notes: entry.plant_notes || '',
  }));
}

function plantsExportRowsForScope(scope) {
  if (scope === 'catalogue_all') return catalogueExportRows(plants);
  if (scope === 'catalogue_page') return catalogueExportRows(lastPagePlants);
  if (scope === 'favorites') return catalogueExportRows(plants.filter(plant => favoriteIds.has(plant.id)));
  if (scope === 'library') return libraryExportRows();
  return catalogueExportRows(lastVisiblePlants);
}

function currentPlantsExportPayload() {
  const scope = document.querySelector('#plants-export-scope')?.value || 'catalogue_visible';
  const format = document.querySelector('#plants-export-format')?.value || 'csv';
  const includeHeaders = !!document.querySelector('#plants-export-headers')?.checked;
  const rows = plantsExportRowsForScope(scope);
  const payload = exportPayloadFromRows(rows, format, includeHeaders);
  return { scope, format, includeHeaders, rows, ...payload };
}

function renderPlantsExportPreview() {
  const preview = document.querySelector('#plants-export-preview');
  const meta = document.querySelector('#plants-export-meta');
  if (!preview || !meta) return;
  const payload = currentPlantsExportPayload();
  const scopeLabel = document.querySelector('#plants-export-scope')?.selectedOptions?.[0]?.textContent || payload.scope;
  meta.textContent = payload.rows.length ? `${payload.rows.length} row(s) selected · ${scopeLabel} · ${payload.format.toUpperCase()}` : 'No rows available for this selection.';
  const lines = payload.text.split('\n').slice(0, 14).join('\n');
  preview.textContent = payload.rows.length ? lines : 'No data to preview.';
}

function openPlantsExportModal(defaultScope = 'catalogue_visible') {
  const modal = document.querySelector('#plants-export-modal');
  if (!modal) return;
  const scope = document.querySelector('#plants-export-scope');
  const format = document.querySelector('#plants-export-format');
  const headers = document.querySelector('#plants-export-headers');
  const fileName = document.querySelector('#plants-export-filename');
  if (scope) scope.value = defaultScope;
  if (format) format.value = 'csv';
  if (headers) headers.checked = true;
  if (fileName && !fileName.value.trim()) fileName.value = 'plants-export';
  modal.classList.remove('hidden');
  renderPlantsExportPreview();
}

function closePlantsExportModal() {
  document.querySelector('#plants-export-modal')?.classList.add('hidden');
}

async function renderLibraryView() {
  const list = document.querySelector('#plant-library-list');
  const tasksList = document.querySelector('#care-tasks-list');
  
  if (!list || !tasksList) return;  // Elements don't exist yet
  
  await loadUserPlants();
  await loadCareTasks();
  
  if (!userPlants.length) {
    list.innerHTML = '<p class="text-stone-500 col-span-full">No plants in your library yet. Add plants from the catalogue or create custom entries.</p>';
  } else {
    list.innerHTML = userPlants.map(plant => {
      const plantInfo = plants.find(p => p.id === plant.plant_id) || {};
      const tasks = careTasks.filter(t => t.user_plant_id === plant.id);
      const nextTask = tasks.length ? tasks.sort((a, b) => new Date(a.next_due_date) - new Date(b.next_due_date))[0] : null;
      return `<div class="rounded-lg border border-stone-200 p-4">
        <div class="flex items-start justify-between gap-3">
          <div class="flex-1">
            <h3 class="font-bold text-stone-900">${escapeHtml(plant.plant_name)}</h3>
            <p class="text-sm text-stone-500">${plantInfo.scientific_name ? escapeHtml(plantInfo.scientific_name) : 'Custom plant'}</p>
            ${plant.location_name ? `<p class="mt-1 text-sm text-emerald-700">📍 ${escapeHtml(plant.location_name)}</p>` : ''}
            ${plant.plant_notes ? `<p class="mt-2 text-sm italic text-stone-600">"${escapeHtml(plant.plant_notes)}"</p>` : ''}
            <div class="mt-2 text-xs text-stone-500">
              <p>Health: <span class="font-bold">${escapeHtml(plant.health_status || 'good')}</span></p>
              ${nextTask ? `<p>Next: ${escapeHtml(nextTask.task_type)} on ${new Date(nextTask.next_due_date).toLocaleDateString()}</p>` : '<p>No care tasks scheduled</p>'}
            </div>
          </div>
          <div class="flex gap-2">
            <button class="edit-plant-btn text-emerald-700 hover:text-emerald-900" data-plant-id="${plant.id}" title="Edit">✎</button>
            <button class="delete-plant-btn text-red-700 hover:text-red-900" data-plant-id="${plant.id}" title="Delete">🗑</button>
          </div>
        </div>
      </div>`;
    }).join('');
    
    list.querySelectorAll('.edit-plant-btn').forEach(btn => btn.addEventListener('click', async () => {
      const plant = userPlants.find(p => p.id === parseInt(btn.dataset.plantId));
      if (!plant) return;
      const newNotes = await askPrompt('Plant notes:', plant.plant_notes || '', 'Edit plant notes');
      if (newNotes !== null) {
        await updateUserPlant(plant.id, { plant_notes: newNotes });
        renderLibraryView();
      }
    }));
    
    list.querySelectorAll('.delete-plant-btn').forEach(btn => btn.addEventListener('click', async () => {
      if (await askConfirm('Remove this plant from your library?', true)) {
        await deleteUserPlant(btn.dataset.plantId);
        renderLibraryView();
      }
    }));
  }
  
  // Render care tasks
  const sortedTasks = [...careTasks].sort((a, b) => new Date(a.next_due_date) - new Date(b.next_due_date));
  const overdue = sortedTasks.filter(t => new Date(t.next_due_date) < new Date() && t.status !== 'completed');
  const upcoming = sortedTasks.filter(t => new Date(t.next_due_date) >= new Date());
  
  if (!sortedTasks.length) {
    tasksList.innerHTML = '<p class="text-stone-500">No care tasks. Create tasks in your plant library.</p>';
  } else {
    const html = [];
    if (overdue.length) {
      html.push(`<div class="rounded-lg border-l-4 border-red-500 bg-red-50 p-3"><p class="font-bold text-red-900">Overdue (${overdue.length})</p></div>`);
      html.push(overdue.map(task => {
        const plant = userPlants.find(p => p.id === task.user_plant_id);
        return `<div class="flex items-center gap-3 rounded-lg bg-red-100 p-3">
          <input type="checkbox" class="complete-task-check" data-task-id="${task.id}">
          <div class="flex-1"><p class="font-semibold text-stone-900">${plant ? escapeHtml(plant.plant_name) : 'Unknown'}</p><p class="text-sm text-stone-600">${escapeHtml(task.task_type)}</p></div>
          <span class="text-xs font-bold text-red-700">DUE</span>
        </div>`;
      }).join(''));
    }
    if (upcoming.length) {
      html.push(upcoming.map(task => {
        const plant = userPlants.find(p => p.id === task.user_plant_id);
        const daysUntil = Math.ceil((new Date(task.next_due_date) - new Date()) / (1000 * 60 * 60 * 24));
        return `<div class="flex items-center gap-3 rounded-lg bg-stone-50 p-3">
          <input type="checkbox" class="complete-task-check" data-task-id="${task.id}">
          <div class="flex-1"><p class="font-semibold text-stone-900">${plant ? escapeHtml(plant.plant_name) : 'Unknown'}</p><p class="text-sm text-stone-600">${escapeHtml(task.task_type)}</p></div>
          <span class="text-xs text-stone-600">in ${daysUntil} day${daysUntil === 1 ? '' : 's'}</span>
        </div>`;
      }).join(''));
    }
    tasksList.innerHTML = html.join('');
    
    tasksList.querySelectorAll('.complete-task-check').forEach(check => check.addEventListener('change', async (e) => {
      if (e.target.checked) {
        await completeTask(e.target.dataset.taskId);
        renderLibraryView();
      }
    }));
  }
}


function importStatusMessage(message) { const target = document.querySelector('#plants-status'); if (target) target.textContent = message; }

document.querySelectorAll('.category-tab').forEach(tab => tab.addEventListener('click', () => { category = tab.dataset.category; renderPlants(); }));
document.querySelectorAll('.plant-view-tab').forEach(tab => tab.addEventListener('click', () => {
  plantView = tab.dataset.view;
  document.querySelector('#catalogue-view').classList.toggle('hidden', plantView !== 'catalogue');
  document.querySelector('#favorites-view').classList.toggle('hidden', plantView !== 'favorites');
  document.querySelector('#library-view').classList.toggle('hidden', plantView !== 'library');
  document.querySelectorAll('.plant-view-tab').forEach(item => {
    const active = item.dataset.view === plantView;
    item.classList.toggle('is-active', active);
    item.setAttribute('aria-selected', String(active));
  });
  if (plantView === 'favorites') renderFavorites();
  if (plantView === 'library') renderLibraryView();
}));
document.querySelector('#plant-view-cards')?.addEventListener('click', () => setPlantDisplayMode('cards'));
document.querySelector('#plant-view-list')?.addEventListener('click', () => setPlantDisplayMode('list'));
setPlantDisplayMode(plantDisplayMode);

// Debounced search handler to avoid excessive filtering on every keystroke
const debouncedSearch = debounce((value) => {
  const sanitised = String(value || '').trim().replace(/\s+/g, ' ');
  filters.search = sanitised;
  updateSearchSuggestion();
  renderPlants();
}, 300);

document.querySelector('#plant-search')?.addEventListener('input', event => {
  debouncedSearch(event.target.value);
  updateSearchSuggestion();
});
document.querySelector('#search-correction-button')?.addEventListener('click', () => {
  const button = document.querySelector('#search-correction-button');
  const searchInput = document.querySelector('#plant-search');
  if (!button || !searchInput) return;
  const corrected = String(button.dataset.correction || '').trim();
  if (!corrected) return;
  const original = String(searchInput.value || '').trim();
  acceptSearchSuggestion(corrected);
  if (original !== corrected) {
    searchInput.value = corrected;
    filters.search = corrected;
    updateSearchSuggestion();
    renderPlants();
  }
});
document.querySelector('#plant-filters')?.addEventListener('submit', event => {
  event.preventDefault();
  const searchInput = document.querySelector('#plant-search');
  filters.search = String(searchInput?.value || '').trim().replace(/\s+/g, ' ');
  updateSearchSuggestion();
  renderPlants();
});
document.querySelector('#safety-filter')?.addEventListener('change', event => { filters.safety = event.target.value; renderPlants(); });
document.querySelector('#season-filter')?.addEventListener('change', event => { filters.season = event.target.value; renderPlants(); });
document.querySelector('#lifecycle-filter')?.addEventListener('change', event => { filters.lifecycle = event.target.value; renderPlants(); });
document.querySelector('#light-filter')?.addEventListener('change', event => { filters.light = event.target.value; renderPlants(); });
document.querySelectorAll('[data-colour-group]').forEach(button => {
  button.addEventListener('click', () => {
    const groupKey = button.dataset.colourGroup;
    const value = String(button.dataset.colourValue || 'all').toLowerCase();
    if (!groupKey) return;
    if (value === 'all') {
      filters[groupKey] = [];
    } else {
      const current = new Set(normaliseColourValues(filters[groupKey]));
      if (current.has(value)) current.delete(value);
      else current.add(value);
      filters[groupKey] = [...current];
    }
    renderPlants();
  });
});
document.querySelector('#missing-plants-review')?.addEventListener('click', () => {
  filters.reviewOnly = !filters.reviewOnly;
  renderPlants();
});
document.querySelector('#height-filter')?.addEventListener('change', event => { filters.height = event.target.value; renderPlants(); });
document.querySelector('#spread-filter')?.addEventListener('change', event => { filters.spread = event.target.value; renderPlants(); });
document.querySelector('#tenderness-filter')?.addEventListener('change', event => { filters.tenderness = event.target.value; renderPlants(); });
document.querySelector('#container-filter')?.addEventListener('change', event => { filters.container = event.target.value; renderPlants(); });
document.querySelector('#watering-filter')?.addEventListener('change', event => { filters.watering = event.target.value; renderPlants(); });
document.querySelector('#pollinator-filter')?.addEventListener('change', event => { filters.pollinator = event.target.value; renderPlants(); });
document.querySelector('#fragrance-filter')?.addEventListener('change', event => { filters.fragrance = event.target.value; renderPlants(); });
document.querySelector('#habit-filter')?.addEventListener('change', event => { filters.habit = event.target.value; renderPlants(); });
document.querySelectorAll('[data-habitat-chip]').forEach(button => {
  button.addEventListener('click', () => {
    const value = button.dataset.habitatChip;
    const selected = new Set(selectedHabitats());
    if (selected.has(value)) {
      selected.delete(value);
    } else {
      selected.add(value);
    }
    filters.habitats = [...selected];
    renderPlants();
  });
});
document.querySelector('#favorites-filter')?.addEventListener('change', event => { filters.favorites = event.target.checked; renderPlants(); });
document.querySelector('#hide-trees-filter')?.addEventListener('change', event => { filters.hideTrees = event.target.checked; renderPlants(); });
document.querySelector('#show-toxic-filter')?.addEventListener('change', event => { filters.showToxic = event.target.checked; renderPlants(); });
document.querySelector('#watering-filter')?.addEventListener('change', event => { filters.watering = event.target.value; renderPlants(); });
document.querySelector('#pollinator-filter')?.addEventListener('change', event => { filters.pollinator = event.target.value; renderPlants(); });
document.querySelector('#fragrance-filter')?.addEventListener('change', event => { filters.fragrance = event.target.value; renderPlants(); });
document.querySelector('#habit-filter')?.addEventListener('change', event => { filters.habit = event.target.value; renderPlants(); });
document.querySelector('#climate-lookup-button')?.addEventListener('click', () => {
  const postcode = document.querySelector('#climate-postcode-input')?.value.trim();
  if (postcode) {
    lookupClimateZone(postcode);
  } else {
    document.querySelector('#climate-status').textContent = 'Please enter a postcode';
  }
});
document.querySelector('#climate-postcode-input')?.addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    document.querySelector('#climate-lookup-button')?.click();
  }
});
document.querySelector('#clear-plant-filters')?.addEventListener('click', () => {
  category = 'all';
  filters.search = '';
  filters.safety = 'all';
  filters.season = 'all';
  filters.lifecycle = 'all';
  filters.light = 'all';
  filters.flowerColour = [];
  filters.foliageColour = [];
  filters.colourPattern = [];
  filters.reviewOnly = false;
  filters.height = 'all';
  filters.spread = 'all';
  filters.tenderness = 'all';
  filters.container = 'all';
  filters.watering = 'all';
  filters.pollinator = 'all';
  filters.fragrance = 'all';
  filters.habit = 'all';
  filters.habitats = ['indoor', 'outdoor'];
  filters.favorites = false;
  filters.hideTrees = true;
  filters.showToxic = false;
  filters.climateZone = null;
  document.querySelector('#plant-search').value = '';
  updateSearchSuggestion();
  document.querySelector('#safety-filter').value = 'all';
  document.querySelector('#season-filter').value = 'all';
  document.querySelector('#lifecycle-filter').value = 'all';
  document.querySelector('#light-filter').value = 'all';
  document.querySelector('#height-filter').value = 'all';
  document.querySelector('#spread-filter').value = 'all';
  document.querySelector('#tenderness-filter').value = 'all';
  document.querySelector('#container-filter').value = 'all';
  document.querySelector('#watering-filter').value = 'all';
  document.querySelector('#pollinator-filter').value = 'all';
  document.querySelector('#fragrance-filter').value = 'all';
  document.querySelector('#habit-filter').value = 'all';
  document.querySelector('#favorites-filter').checked = false;
  document.querySelector('#hide-trees-filter').checked = true;
  document.querySelector('#show-toxic-filter').checked = false;
  setReviewModeState(false);
  clearClimateZone();
});
document.querySelector('#export-plants-button')?.addEventListener('click', () => openPlantsExportModal('catalogue_all'));
document.querySelector('#plants-export-close')?.addEventListener('click', closePlantsExportModal);
document.querySelector('#plants-export-cancel')?.addEventListener('click', closePlantsExportModal);
document.querySelector('#plants-export-modal')?.addEventListener('click', event => {
  if (event.target.id === 'plants-export-modal') closePlantsExportModal();
});
document.querySelector('#plants-export-scope')?.addEventListener('change', renderPlantsExportPreview);
document.querySelector('#plants-export-format')?.addEventListener('change', renderPlantsExportPreview);
document.querySelector('#plants-export-headers')?.addEventListener('change', renderPlantsExportPreview);
document.querySelector('#plants-export-download')?.addEventListener('click', async () => {
  const payload = currentPlantsExportPayload();
  if (!payload.rows.length) {
    await showAlert('No rows available for this export option.', 'Nothing to export');
    return;
  }
  const filenameInput = document.querySelector('#plants-export-filename');
  const base = (filenameInput?.value || 'plants-export').trim().replace(/[\\/:*?"<>|]+/g, '-');
  const extension = ({ json: 'json', tsv: 'tsv', csv: 'csv', ndjson: 'ndjson', markdown: 'md', html: 'html' }[payload.format] || 'txt');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([payload.text], { type: payload.mime }));
  link.download = `${base || 'plants-export'}.${extension}`;
  link.click();
  URL.revokeObjectURL(link.href);
  closePlantsExportModal();
  await showAlert(`Exported ${payload.rows.length} row(s) as ${extension.toUpperCase()}.`, 'Export complete');
});
document.querySelector('#hide-trees-filter') && (document.querySelector('#hide-trees-filter').checked = filters.hideTrees);
document.querySelector('#plant-dark-toggle')?.addEventListener('change', event => {
  applyPlantDarkMode(!!event.target.checked);
});
const storedDarkMode = localStorage.getItem('plantDarkMode') === '1';
applyPlantDarkMode(storedDarkMode);

// Setup dropdown menu
const menuToggle = document.querySelector('#plant-menu-toggle');
const menuContent = document.querySelector('#plant-menu');
if (menuToggle && menuContent) {
  menuToggle.addEventListener('click', (e) => {
    e.stopPropagation();
    menuContent.classList.toggle('hidden');
    menuToggle.setAttribute('aria-expanded', String(!menuContent.classList.contains('hidden')));
  });
  
  // Close menu when clicking on a menu item
  menuContent.querySelectorAll('.dropdown-item').forEach(item => {
    item.addEventListener('click', () => {
      if (!item.href || item.target === '_blank') {
        menuContent.classList.add('hidden');
        menuToggle.setAttribute('aria-expanded', 'false');
      }
    });
  });
  
  // Close menu when clicking outside
  document.addEventListener('click', (e) => {
    if (!e.target.closest('#plant-menu-toggle') && !e.target.closest('#plant-menu')) {
      menuContent.classList.add('hidden');
      menuToggle.setAttribute('aria-expanded', 'false');
    }
  });
}

setupPlantImport();
document.addEventListener('click', event => {
  if (event.target.closest('#plant-profile-close') || event.target.id === 'plant-profile-modal') document.querySelector('#plant-profile-modal')?.classList.add('hidden');
});
document.querySelector('#export-library-csv')?.addEventListener('click', () => { const rows = [['Name','Scientific name','Category','Safety','Next watering']].concat(plants.filter(plant => favoriteIds.has(plant.id)).map(plant => [plant.name,plant.scientific_name,plant.category,plant.safety_status,care[plant.id]?.watering || ''])); const csv = rows.map(row => row.map(value => `"${String(value).replaceAll('"','""')}"`).join(',')).join('\n'); const link = document.createElement('a'); link.href = URL.createObjectURL(new Blob([csv], {type:'text/csv'})); link.download = 'my-plant-library.csv'; link.click(); URL.revokeObjectURL(link.href); });
document.querySelector('#print-library')?.addEventListener('click', () => window.print());

Promise.all([
  fetch('/api/dog-safe-plants').then(response => {
    if (!response.ok) throw new Error('Could not load plant data.');
    return response.json();
  }),
  loadProfileOverrides(),
  loadLifecycleHardinessOverrides(),
  loadToxicityEvidenceOverrides(),
  loadPlantSynonymOverrides(),
  loadPlantColourOverrides(),
  loadPlantReviewQueue(),
  loadSpellcheckDictionary(),
  loadLibrary(),
  loadUserPlants(),
  loadCareTasks()
]).then(([data]) => {
  console.log('✓ Promise.all resolved, data:', data);
  plants = Array.isArray(data.plants) ? data.plants : [];
  console.log('✓ Plants loaded:', plants.length);
  
  // Restore previously selected climate zone
  if (selectedClimateZone) {
    filters.climateZone = selectedClimateZone;
    const postcodeInput = document.querySelector('#climate-postcode-input');
    if (postcodeInput) postcodeInput.value = selectedPostcode;
    const zoneDisplay = document.querySelector('#climate-zone-display');
    if (zoneDisplay) {
      zoneDisplay.innerHTML = `<div class="rounded bg-white p-2"><p class="font-semibold text-stone-900">${selectedClimateZone}</p></div>`;
    }
    const statusEl = document.querySelector('#climate-status');
    if (statusEl) statusEl.textContent = `Showing plants suitable for ${selectedClimateZone}`;
  }
  
  console.log('✓ About to render plants');
  renderPlants();
  console.log('✓ Rendered plants');
  renderLibraryView();
  // Only render favorites if the element exists (i.e., we're not on catalogue view)
  const favList = document.querySelector('#plant-favorites-list');
  if (favList) renderFavorites();
  setupLibraryEventListeners();
  console.log('✓ Setup complete');
  
  // Setup pagination event listeners (attach once after data loads)
  document.querySelector('#pagination-prev')?.addEventListener('click', () => {
    if (currentPage > 1) {
      currentPage--;
      renderPlants();
      document.querySelector('#plant-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  
  document.querySelector('#pagination-next')?.addEventListener('click', () => {
    if (currentPage < totalPages) {
      currentPage++;
      renderPlants();
      document.querySelector('#plant-grid')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  });
  console.log('✓ Pagination listeners attached');
}).catch(error => { 
  console.error('✗ Promise.all error:', error);
  const statusEl = document.querySelector('#plants-status');
  if (statusEl) statusEl.textContent = error.message;
});

function setupLibraryEventListeners() {
  const modal = document.querySelector('#add-plant-modal');
  const form = document.querySelector('#add-plant-form');
  const status = document.querySelector('#add-plant-status');
  const select = document.querySelector('#add-plant-select');
  const locationInput = form?.querySelector('[name="location_name"]');
  const zoneInput = form?.querySelector('[name="location_zone"]');
  const dateInput = form?.querySelector('[name="date_planted"]');
  const qtyInput = document.querySelector('#add-plant-qty-input');
  const saveAnotherButton = document.querySelector('#save-add-another-button');
  const selectedLabel = document.querySelector('#add-plant-selected');

  const refreshLocationSuggestions = () => {
    const locationList = document.querySelector('#location-name-suggestions');
    const zoneList = document.querySelector('#location-zone-suggestions');
    if (!locationList || !zoneList) return;
    const locations = [...new Set(userPlants.map(item => (item.location_name || '').trim()).filter(Boolean))].sort();
    const zones = [...new Set(userPlants.map(item => (item.location_zone || '').trim()).filter(Boolean))].sort();
    locationList.innerHTML = locations.map(item => `<option value="${escapeHtml(item)}"></option>`).join('');
    zoneList.innerHTML = zones.map(item => `<option value="${escapeHtml(item)}"></option>`).join('');
  };

  const updateDuplicateWarning = () => {
    if (!status || !select || !locationInput) return;
    const plant = plants.find(item => item.id === select.value);
    const location = locationInput.value.trim().toLowerCase();
    if (!plant || !location) return;
    const duplicate = userPlants.find(item => String(item.plant_id) === String(plant.id) && (item.location_name || '').trim().toLowerCase() === location);
    if (duplicate) {
      status.textContent = `You already have ${plant.name} in ${duplicate.location_name || 'this location'}. You can still save another entry.`;
      status.className = 'mt-3 text-sm text-amber-700';
    }
  };

  const openAddPlantModal = async () => {
    if (!modal || !form || !select || !selectedLabel) return;
    addPlantModalDirty = false;
    saveAndAddAnother = false;
    pickerCategory = 'all';
    await loadUserPlants();
    refreshLocationSuggestions();
    form.reset();
    status.textContent = '';
    status.className = 'mt-3 text-sm';
    select.value = '';
    selectedLabel.textContent = 'No plant selected';
    const summary = document.querySelector('#add-plant-summary');
    if (summary) summary.classList.add('hidden');
    const today = new Date().toISOString().slice(0, 10);
    if (dateInput) dateInput.value = today;
    if (qtyInput) qtyInput.value = '1';
    renderPlantCategoryFilters();
    renderPlantPicker('');
    modal.classList.remove('hidden');
  };

  const closeAddPlantModal = async () => {
    if (!modal || !form) return;
    if (addPlantModalDirty) {
      const approved = await askConfirm('Discard unsaved plant form changes?', true);
      if (!approved) return;
    }
    modal.classList.add('hidden');
    addPlantModalDirty = false;
  };

  const addBtn = document.querySelector('#add-new-plant-button');
  if (addBtn) {
    addBtn.addEventListener('click', openAddPlantModal);
  }
  document.querySelector('#add-plant-search')?.addEventListener('input', event => renderPlantPicker(event.target.value));
  document.querySelector('#add-plant-close')?.addEventListener('click', closeAddPlantModal);
  modal?.addEventListener('click', event => {
    if (event.target === modal) closeAddPlantModal();
  });
  document.querySelector('#add-plant-form')?.addEventListener('input', () => {
    addPlantModalDirty = true;
    updateDuplicateWarning();
  });
  locationInput?.addEventListener('input', updateDuplicateWarning);
  saveAnotherButton?.addEventListener('click', () => {
    saveAndAddAnother = true;
    form?.requestSubmit();
  });
  document.querySelector('#add-plant-date-today')?.addEventListener('click', () => {
    if (!dateInput) return;
    dateInput.value = new Date().toISOString().slice(0, 10);
    addPlantModalDirty = true;
  });
  document.querySelector('#add-plant-date-last-week')?.addEventListener('click', () => {
    if (!dateInput) return;
    const date = new Date();
    date.setDate(date.getDate() - 7);
    dateInput.value = date.toISOString().slice(0, 10);
    addPlantModalDirty = true;
  });
  document.querySelector('#add-plant-qty-dec')?.addEventListener('click', () => {
    if (!qtyInput) return;
    const current = Math.max(1, Number(qtyInput.value) || 1);
    qtyInput.value = String(Math.max(1, current - 1));
    addPlantModalDirty = true;
  });
  document.querySelector('#add-plant-qty-inc')?.addEventListener('click', () => {
    if (!qtyInput) return;
    const current = Math.max(1, Number(qtyInput.value) || 1);
    qtyInput.value = String(current + 1);
    addPlantModalDirty = true;
  });
  document.querySelector('#add-plant-form')?.addEventListener('submit', async event => {
    event.preventDefault();
    if (!form || !status) return;
    const data = Object.fromEntries(new FormData(form));
    const plant = plants.find(item => item.id === data.plant_id);
    if (!plant) {
      status.textContent = 'Please select a plant first.';
      status.className = 'mt-3 text-sm text-red-700';
      return;
    }
    if (!String(data.location_name || '').trim()) {
      status.textContent = 'Please enter a location name.';
      status.className = 'mt-3 text-sm text-red-700';
      return;
    }
    if (!data.date_planted) {
      data.date_planted = new Date().toISOString().slice(0, 10);
    }
    const quantity = Math.max(1, Number(data.quantity_planted) || 1);
    data.quantity_planted = String(quantity);
    const result = await fetch('/api/user-plants', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ user_id: userId, plant_id: data.plant_id, plant_name: plant.name, ...data })
    });
    const body = await result.json();
    if (!result.ok) {
      status.textContent = body.error || 'Could not save plant.';
      status.className = 'mt-3 text-sm text-red-700';
      return;
    }
    await createCareTask(body.id, 'water', 7);
    status.textContent = `${plant.name} added to My Garden.`;
    status.className = 'mt-3 text-sm text-emerald-700';
    await renderLibraryView();
    refreshLocationSuggestions();
    addPlantModalDirty = false;
    if (saveAndAddAnother) {
      saveAndAddAnother = false;
      const preservedLocation = locationInput?.value || '';
      const preservedZone = zoneInput?.value || '';
      form.reset();
      if (locationInput) locationInput.value = preservedLocation;
      if (zoneInput) zoneInput.value = preservedZone;
      if (dateInput) dateInput.value = new Date().toISOString().slice(0, 10);
      if (qtyInput) qtyInput.value = '1';
      select.value = '';
      if (selectedLabel) selectedLabel.textContent = 'No plant selected';
      const summary = document.querySelector('#add-plant-summary');
      if (summary) summary.classList.add('hidden');
      renderPlantPicker('');
      status.textContent = 'Saved. Add another plant entry.';
      status.className = 'mt-3 text-sm text-emerald-700';
      return;
    }
    setTimeout(() => { modal?.classList.add('hidden'); }, 500);
  });
  
  const exportBtn = document.querySelector('#export-library-csv');
  if (exportBtn) exportBtn.addEventListener('click', () => openPlantsExportModal('library'));
}

function scrollPlantListToTop() {
  const target = document.querySelector('#plant-grid') || document.querySelector('#plants-status');
  if (!target) return;
  target.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function updatePagination(totalPages, totalItems) {
  const prevBtn = document.querySelector('#pagination-prev');
  const nextBtn = document.querySelector('#pagination-next');
  const pagesContainer = document.querySelector('#pagination-pages');
  const pagination = document.querySelector('#plant-pagination');
  
  // Show/hide pagination based on total pages
  pagination.hidden = totalPages <= 1;
  if (totalPages <= 1) return;
  
  // Update prev/next buttons
  prevBtn.disabled = currentPage === 1;
  nextBtn.disabled = currentPage === totalPages;

  const goToPage = (pageNumber) => {
   if (pageNumber < 1 || pageNumber > totalPages || pageNumber === currentPage) return;
   currentPage = pageNumber;
   renderPlants();
   scrollPlantListToTop();
  };

  prevBtn.onclick = () => goToPage(currentPage - 1);
  nextBtn.onclick = () => goToPage(currentPage + 1);
  
  // Generate page buttons
  const maxPagesToShow = window.innerWidth < 640 ? 3 : 5;
  let startPage = Math.max(1, currentPage - Math.floor(maxPagesToShow / 2));
  let endPage = Math.min(totalPages, startPage + maxPagesToShow - 1);
  
  if (endPage - startPage + 1 < maxPagesToShow) {
   startPage = Math.max(1, endPage - maxPagesToShow + 1);
  }
  
  pagesContainer.innerHTML = '';
  
  if (startPage > 1) {
   const btn = document.createElement('button');
   btn.type = 'button';
   btn.className = 'pagination-page';
   btn.textContent = '1';
   btn.addEventListener('click', () => goToPage(1));
   pagesContainer.appendChild(btn);
     
   if (startPage > 2) {
     const dots = document.createElement('span');
     dots.textContent = '...';
     dots.style.padding = '0.6rem 0.4rem';
     dots.style.color = 'var(--muted)';
     pagesContainer.appendChild(dots);
   }
  }
  
  for (let i = startPage; i <= endPage; i++) {
   const btn = document.createElement('button');
   btn.type = 'button';
   btn.className = `pagination-page ${i === currentPage ? 'active' : ''}`;
   btn.textContent = i;
   btn.addEventListener('click', () => goToPage(i));
   pagesContainer.appendChild(btn);
  }
  
  if (endPage < totalPages) {
   if (endPage < totalPages - 1) {
     const dots = document.createElement('span');
     dots.textContent = '...';
     dots.style.padding = '0.6rem 0.4rem';
     dots.style.color = 'var(--muted)';
     pagesContainer.appendChild(dots);
   }
     
   const btn = document.createElement('button');
   btn.type = 'button';
   btn.className = 'pagination-page';
   btn.textContent = totalPages;
   btn.addEventListener('click', () => goToPage(totalPages));
   pagesContainer.appendChild(btn);
  }
}

function renderPlantPicker(search) {
  const results = document.querySelector('#add-plant-results');
  const select = document.querySelector('#add-plant-select');
  if (!results || !select) return;
  const query = search.trim().toLowerCase();
  const matches = plants.filter(plant => {
    const searchable = `${plant.name} ${plant.scientific_name} ${getPlantSynonyms(plant).join(' ')}`.toLowerCase();
    const categoryMatch = pickerCategory === 'all' || plant.category === pickerCategory;
    return searchable.includes(query) && categoryMatch;
  }).slice(0, 40);
  results.innerHTML = matches.map(plant => `<button type="button" class="plant-picker-item" data-picker-id="${escapeHtml(plant.id)}">${imageSources(plant)[0] ? `<img src="${escapeHtml(imageSources(plant)[0])}" alt="" loading="lazy">` : ''}<span><strong>${escapeHtml(plant.name)}</strong><small>${escapeHtml(plant.scientific_name)} · ${escapeHtml(plant.category)}</small></span></button>`).join('') || '<p class="text-sm text-stone-500">No plants found.</p>';
  results.querySelectorAll('[data-picker-id]').forEach(button => button.addEventListener('click', () => {
    const plant = plants.find(item => item.id === button.dataset.pickerId);
    if (!plant) return;
    select.innerHTML = `<option value="${escapeHtml(plant.id)}">${escapeHtml(plant.name)}</option>`;
    select.value = plant.id;
    document.querySelector('#add-plant-selected').textContent = `Selected: ${plant.name}`;
    const summary = document.querySelector('#add-plant-summary');
    const summaryImage = document.querySelector('#add-plant-summary-image');
    const summaryName = document.querySelector('#add-plant-summary-name');
    const summaryScientific = document.querySelector('#add-plant-summary-scientific');
    if (summary && summaryImage && summaryName && summaryScientific) {
      summary.classList.remove('hidden');
      summaryImage.src = imageSources(plant)[0] || '/static/plant-placeholder.svg';
      summaryImage.onerror = () => { summaryImage.src = '/static/plant-placeholder.svg'; };
      summaryName.textContent = plant.name;
      summaryScientific.textContent = `${plant.scientific_name || ''} · ${plant.category || ''}`;
    }
    results.querySelectorAll('.plant-picker-item').forEach(item => item.classList.remove('is-selected'));
    button.classList.add('is-selected');
    addPlantModalDirty = true;
  }));
}

function renderPlantCategoryFilters() {
  const container = document.querySelector('#add-plant-category-filters');
  if (!container) return;
  const categories = ['all', ...new Set(plants.map(plant => plant.category).filter(Boolean))];
  container.innerHTML = categories.map(categoryOption => `<button type="button" class="chip-button ${pickerCategory === categoryOption ? 'is-active' : ''}" data-picker-category="${escapeHtml(categoryOption)}">${categoryOption === 'all' ? 'All categories' : categoryOption[0].toUpperCase() + categoryOption.slice(1)}</button>`).join('');
  container.querySelectorAll('[data-picker-category]').forEach(button => button.addEventListener('click', () => {
    pickerCategory = button.dataset.pickerCategory;
    renderPlantCategoryFilters();
    renderPlantPicker(document.querySelector('#add-plant-search')?.value || '');
  }));
}
