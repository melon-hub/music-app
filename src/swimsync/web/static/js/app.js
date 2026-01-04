/**
 * Swim Sync Web UI - Application Logic
 */

// State
let currentPlaylist = null;
let syncPreview = null;
let isSyncing = false;
let syncPollInterval = null;
let pollErrorCount = 0;

// DOM Elements
const elements = {
    // Navigation
    navItems: document.querySelectorAll('.nav-item'),
    views: document.querySelectorAll('.view'),

    // Dashboard
    playlistUrl: document.getElementById('playlist-url'),
    loadBtn: document.getElementById('load-btn'),
    outputFolder: document.getElementById('output-folder'),
    browseBtn: document.getElementById('browse-btn'),

    // Playlist
    emptyState: document.getElementById('empty-state'),
    loadingState: document.getElementById('loading-state'),
    trackListContainer: document.getElementById('track-list-container'),
    trackList: document.getElementById('track-list'),
    playlistName: document.getElementById('playlist-name'),
    trackCount: document.getElementById('track-count'),

    // Storage
    storageUsed: document.getElementById('storage-used'),
    storageLimit: document.getElementById('storage-limit'),
    storageFill: document.getElementById('storage-fill'),
    storagePercent: document.getElementById('storage-percent'),
    syncSummary: document.getElementById('sync-summary'),

    // Actions
    syncBtn: document.getElementById('sync-btn'),
    cancelBtn: document.getElementById('cancel-btn'),
    deleteRemovedToggle: document.getElementById('delete-removed-toggle'),

    // Sync Panel
    syncPanel: document.getElementById('sync-panel'),
    syncPercent: document.getElementById('sync-percent'),
    syncPercentInner: document.getElementById('sync-percent-inner'),
    progressCircle: document.getElementById('progress-circle'),
    syncCurrentTrack: document.getElementById('sync-current-track'),
    syncSpeed: document.getElementById('sync-speed'),
    syncEta: document.getElementById('sync-eta'),

    // Settings
    settingBitrate: document.getElementById('setting-bitrate'),
    settingStorageLimit: document.getElementById('setting-storage-limit'),
    settingTimeout: document.getElementById('setting-timeout'),
    saveSettingsBtn: document.getElementById('save-settings-btn')
};

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    setupEventListeners();
    await loadConfig();
    await updateStorageDisplay();
}

function setupEventListeners() {
    // Navigation
    elements.navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const view = item.dataset.view;
            switchView(view);
        });
    });

    // Load playlist
    elements.loadBtn.addEventListener('click', loadPlaylist);
    elements.playlistUrl.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') loadPlaylist();
    });

    // Browse folder (note: web browsers can't access local filesystem directly)
    elements.browseBtn.addEventListener('click', () => {
        alert('Folder selection is managed through the Settings page.\nThe output folder path is configured on the server.');
    });

    // Sync actions
    elements.syncBtn.addEventListener('click', startSync);
    elements.cancelBtn.addEventListener('click', cancelSync);

    // Settings
    elements.saveSettingsBtn.addEventListener('click', saveSettings);

    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 's') {
            e.preventDefault();
            if (!elements.syncBtn.disabled) startSync();
        }
        if (e.key === 'Escape' && isSyncing) {
            cancelSync();
        }
    });
}

function switchView(viewName) {
    // Update nav
    elements.navItems.forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewName);
    });

    // Update views
    elements.views.forEach(view => {
        view.classList.toggle('active', view.id === `${viewName}-view`);
        view.classList.toggle('hidden', view.id !== `${viewName}-view`);
    });
}

// API Functions
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            alert(`Failed to load configuration: ${data.error || response.statusText}`);
            return;
        }
        const config = await response.json();

        elements.outputFolder.value = config.output_folder;
        elements.playlistUrl.value = config.last_playlist_url || '';
        elements.deleteRemovedToggle.checked = config.auto_delete_removed;

        // Settings
        elements.settingBitrate.value = config.bitrate;
        elements.settingStorageLimit.value = config.storage_limit_gb;
        elements.settingTimeout.value = config.download_timeout;
    } catch (error) {
        console.error('Failed to load config:', error);
        alert(`Failed to load configuration: ${error.message}`);
    }
}

async function loadPlaylist() {
    const url = elements.playlistUrl.value.trim();

    if (!url) {
        alert('Please enter a Spotify playlist URL');
        return;
    }

    if (!url.includes('open.spotify.com/playlist')) {
        alert('Please enter a valid Spotify playlist URL');
        return;
    }

    // Show loading state
    elements.emptyState.classList.add('hidden');
    elements.trackListContainer.classList.add('hidden');
    elements.loadingState.classList.remove('hidden');
    elements.loadBtn.disabled = true;

    try {
        const response = await fetch('/api/playlist/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to load playlist');
        }

        currentPlaylist = data;
        syncPreview = data.preview;

        displayPlaylist(data);
        updateStorageDisplay(data.storage);
        updateSyncSummary();

    } catch (error) {
        alert(`Error: ${error.message}`);
        elements.emptyState.classList.remove('hidden');
    } finally {
        elements.loadingState.classList.add('hidden');
        elements.loadBtn.disabled = false;
    }
}

function displayPlaylist(data) {
    elements.playlistName.textContent = data.playlist_name;
    elements.trackCount.textContent = `${data.tracks.length} tracks`;

    // Clear track list using safe DOM method
    while (elements.trackList.firstChild) {
        elements.trackList.removeChild(elements.trackList.firstChild);
    }

    const allTracks = [
        ...data.preview.new.map(t => ({ ...t, status: 'new' })),
        ...data.preview.suspect.map(t => ({ ...t, status: 'suspect' })),
        ...data.preview.existing.map(t => ({ ...t, status: 'exists' })),
        ...data.preview.removed.map(t => ({ ...t, status: 'removed' }))
    ];

    allTracks.forEach(track => {
        const row = document.createElement('tr');

        const titleCell = document.createElement('td');
        titleCell.textContent = track.title;
        row.appendChild(titleCell);

        const artistCell = document.createElement('td');
        artistCell.textContent = track.artist;
        row.appendChild(artistCell);

        const statusCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = `status-badge status-${track.status}`;
        badge.textContent = getStatusLabel(track.status);
        statusCell.appendChild(badge);
        row.appendChild(statusCell);

        elements.trackList.appendChild(row);
    });

    elements.trackListContainer.classList.remove('hidden');

    // Enable sync button if there's work to do
    const hasWork = data.preview.new.length > 0 ||
                    data.preview.suspect.length > 0 ||
                    (data.preview.removed.length > 0 && elements.deleteRemovedToggle.checked);
    elements.syncBtn.disabled = !hasWork;
}

function getStatusLabel(status) {
    const labels = {
        'new': 'New',
        'exists': 'Exists',
        'removed': 'Removed',
        'suspect': 'Suspect'
    };
    return labels[status] || status;
}

function updateSyncSummary() {
    if (!syncPreview) {
        elements.syncSummary.textContent = 'Load a playlist to see sync preview';
        return;
    }

    const newCount = syncPreview.new.length;
    const suspectCount = syncPreview.suspect.length;
    const removedCount = syncPreview.removed.length;
    const downloadCount = newCount + suspectCount;
    const estSize = downloadCount * 8; // ~8MB per track estimate

    let summary = `${currentPlaylist.tracks.length} tracks | ${newCount} new | ${removedCount} removed`;
    if (suspectCount > 0) {
        summary += ` | ${suspectCount} suspect`;
    }
    if (downloadCount > 0) {
        summary += ` | ~${estSize} MB to download`;
    }

    elements.syncSummary.textContent = summary;
}

async function updateStorageDisplay(storage = null) {
    try {
        if (!storage) {
            const response = await fetch('/api/storage');
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                alert(`Failed to load storage info: ${data.error || response.statusText}`);
                return;
            }
            storage = await response.json();
        }

        const usedGb = storage.used_mb / 1024;
        const limitGb = storage.limit_gb || 32;
        const percent = Math.min((usedGb / limitGb) * 100, 100);

        elements.storageUsed.textContent = `${usedGb.toFixed(1)} GB`;
        elements.storageLimit.textContent = `${limitGb} GB`;
        elements.storageFill.style.width = `${percent}%`;
        elements.storagePercent.textContent = `${percent.toFixed(1)}%`;

    } catch (error) {
        console.error('Failed to update storage:', error);
        alert(`Failed to load storage info: ${error.message}`);
    }
}

async function startSync() {
    if (!syncPreview || isSyncing) return;

    const deleteRemoved = elements.deleteRemovedToggle.checked;

    // Confirm deletion
    if (deleteRemoved && syncPreview.removed.length > 0) {
        if (!confirm(`This will delete ${syncPreview.removed.length} track(s) that were removed from the playlist.\n\nContinue?`)) {
            return;
        }
    }

    isSyncing = true;
    pollErrorCount = 0;
    elements.syncBtn.disabled = true;
    elements.cancelBtn.disabled = false;
    elements.loadBtn.disabled = true;

    // Show sync panel
    elements.syncPanel.classList.remove('hidden');

    try {
        const response = await fetch('/api/sync/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                new_tracks: syncPreview.new,
                suspect_tracks: syncPreview.suspect,
                removed_tracks: syncPreview.removed,
                delete_removed: deleteRemoved
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Failed to start sync');
        }

        // Start polling for status
        syncPollInterval = setInterval(pollSyncStatus, 500);

    } catch (error) {
        alert(`Error: ${error.message}`);
        resetSyncState();
    }
}

async function pollSyncStatus() {
    try {
        const response = await fetch('/api/sync/status');
        if (!response.ok) {
            pollErrorCount++;
            console.error(`Failed to poll sync status (attempt ${pollErrorCount}):`, response.statusText);
            if (pollErrorCount >= 3) {
                clearInterval(syncPollInterval);
                alert('Lost connection to server');
                resetSyncState();
            }
            return;
        }

        // Reset error counter on success
        pollErrorCount = 0;

        const status = await response.json();

        updateSyncProgress(status);

        if (!status.is_syncing) {
            clearInterval(syncPollInterval);

            if (status.status === 'completed') {
                alert('Sync completed successfully!');
            } else if (status.status === 'error') {
                alert(`Sync failed: ${status.error}`);
            } else if (status.status === 'cancelled') {
                alert('Sync was cancelled');
            }

            resetSyncState();
            await updateStorageDisplay();
        }

    } catch (error) {
        pollErrorCount++;
        console.error(`Failed to poll sync status (attempt ${pollErrorCount}):`, error);
        if (pollErrorCount >= 3) {
            clearInterval(syncPollInterval);
            alert('Lost connection to server');
            resetSyncState();
        }
    }
}

function updateSyncProgress(status) {
    const percent = status.total > 0 ? Math.round((status.current / status.total) * 100) : 0;

    // Update text
    elements.syncPercent.textContent = `${percent}%`;
    elements.syncPercentInner.textContent = `${percent}%`;
    elements.syncCurrentTrack.textContent = status.current_track || 'Waiting...';
    elements.syncSpeed.textContent = status.speed_mbps > 0 ? `${status.speed_mbps.toFixed(1)} MB/s` : '0 MB/s';

    // Calculate ETA
    if (status.current > 0 && status.total > 0) {
        const remaining = status.total - status.current;
        const avgTimePerTrack = 30; // Rough estimate: 30 seconds per track
        const etaSeconds = remaining * avgTimePerTrack;
        elements.syncEta.textContent = formatTime(etaSeconds);
    } else {
        elements.syncEta.textContent = 'Calculating...';
    }

    // Update progress ring
    const circumference = 2 * Math.PI * 45; // radius = 45
    const offset = circumference - (percent / 100) * circumference;
    elements.progressCircle.style.strokeDashoffset = offset;
}

async function cancelSync() {
    if (!isSyncing) return;

    try {
        const response = await fetch('/api/sync/cancel', { method: 'POST' });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            alert(`Failed to cancel sync: ${data.error || response.statusText}`);
        }
    } catch (error) {
        console.error('Failed to cancel sync:', error);
        alert(`Failed to cancel sync: ${error.message}`);
    }
}

function resetSyncState() {
    isSyncing = false;
    pollErrorCount = 0;
    elements.syncBtn.disabled = false;
    elements.cancelBtn.disabled = true;
    elements.loadBtn.disabled = false;
    elements.syncPanel.classList.add('hidden');

    if (syncPollInterval) {
        clearInterval(syncPollInterval);
        syncPollInterval = null;
    }
}

async function saveSettings() {
    try {
        const response = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                bitrate: elements.settingBitrate.value,
                storage_limit_gb: parseInt(elements.settingStorageLimit.value),
                download_timeout: parseInt(elements.settingTimeout.value)
            })
        });

        if (response.ok) {
            alert('Settings saved successfully!');
            await updateStorageDisplay();
        } else {
            const data = await response.json().catch(() => ({}));
            alert(`Failed to save settings: ${data.error || response.statusText}`);
        }

    } catch (error) {
        alert(`Error: ${error.message}`);
    }
}

// Utility Functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatTime(seconds) {
    if (seconds < 60) {
        return `~${Math.round(seconds)}s`;
    } else if (seconds < 3600) {
        const mins = Math.floor(seconds / 60);
        const secs = Math.round(seconds % 60);
        return secs > 0 ? `~${mins}m ${secs}s` : `~${mins}m`;
    } else {
        const hours = Math.floor(seconds / 3600);
        const mins = Math.floor((seconds % 3600) / 60);
        return mins > 0 ? `~${hours}h ${mins}m` : `~${hours}h`;
    }
}
