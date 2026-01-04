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

    // Playlist Stats Card
    playlistStatsCard: document.getElementById('playlist-stats-card'),
    statTotalTracks: document.getElementById('stat-total-tracks'),
    statDuration: document.getElementById('stat-duration'),
    statEstSize: document.getElementById('stat-est-size'),
    statAvgSize: document.getElementById('stat-avg-size'),
    breakdownExistingCount: document.getElementById('breakdown-existing-count'),
    breakdownExistingSize: document.getElementById('breakdown-existing-size'),
    breakdownNewCount: document.getElementById('breakdown-new-count'),
    breakdownNewSize: document.getElementById('breakdown-new-size'),
    breakdownRemovedCount: document.getElementById('breakdown-removed-count'),

    // Storage (enhanced storage card)
    storageUsed: document.getElementById('storage-used'),
    storageFill: document.getElementById('storage-fill'),
    storageAfterSync: document.getElementById('storage-after-sync'),
    storageDelta: document.getElementById('storage-delta'),
    storageRemaining: document.getElementById('storage-remaining'),
    storageLimitLabel: document.getElementById('storage-limit-label'),
    storageAfterSyncMarker: document.getElementById('storage-after-sync-marker'),

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
    syncCurrentNum: document.getElementById('sync-current-num'),
    syncTotalNum: document.getElementById('sync-total-num'),
    syncDownloadedSize: document.getElementById('sync-downloaded-size'),
    syncTotalSize: document.getElementById('sync-total-size'),
    syncDoneCount: document.getElementById('sync-done-count'),
    syncActiveCount: document.getElementById('sync-active-count'),
    syncLeftCount: document.getElementById('sync-left-count'),

    // Settings
    settingBitrate: document.getElementById('setting-bitrate'),
    settingStorageLimit: document.getElementById('setting-storage-limit'),
    settingTimeout: document.getElementById('setting-timeout'),
    saveSettingsBtn: document.getElementById('save-settings-btn'),

    // Library Stats (Settings page)
    libraryTotalTracks: document.getElementById('library-total-tracks'),
    librarySize: document.getElementById('library-size'),
    libraryAvgSize: document.getElementById('library-avg-size'),
    libraryLastSync: document.getElementById('library-last-sync'),
    libraryDeviceCapacity: document.getElementById('library-device-capacity')
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

    // Update playlist stats card
    updatePlaylistStats(data);

    // Enable sync button if there's work to do
    const hasWork = data.preview.new.length > 0 ||
                    data.preview.suspect.length > 0 ||
                    (data.preview.removed.length > 0 && elements.deleteRemovedToggle.checked);
    elements.syncBtn.disabled = !hasWork;
}

function updatePlaylistStats(data) {
    const totalTracks = data.tracks.length;
    const existingCount = data.preview.existing ? data.preview.existing.length : 0;
    const newCount = data.preview.new ? data.preview.new.length : 0;
    const suspectCount = data.preview.suspect ? data.preview.suspect.length : 0;
    const removedCount = data.preview.removed ? data.preview.removed.length : 0;

    // Estimate sizes (~8MB per track is a reasonable estimate for 192kbps)
    const avgSizeMb = 8;
    const totalEstMb = totalTracks * avgSizeMb;
    const existingSizeMb = existingCount * avgSizeMb;
    const newSizeMb = (newCount + suspectCount) * avgSizeMb;

    // Estimate duration (~3.5 minutes per track average)
    const avgDurationMin = 3.5;
    const totalDurationMin = totalTracks * avgDurationMin;
    const durationHrs = totalDurationMin / 60;

    // Update stats
    if (elements.statTotalTracks) {
        elements.statTotalTracks.textContent = totalTracks;
    }
    if (elements.statDuration) {
        elements.statDuration.textContent = durationHrs >= 1 ? `~${durationHrs.toFixed(1)}h` : `~${Math.round(totalDurationMin)}m`;
    }
    if (elements.statEstSize) {
        elements.statEstSize.textContent = formatSize(totalEstMb * 1024 * 1024);
    }
    if (elements.statAvgSize) {
        elements.statAvgSize.textContent = `~${avgSizeMb} MB`;
    }

    // Update breakdown
    if (elements.breakdownExistingCount) {
        elements.breakdownExistingCount.textContent = existingCount;
    }
    if (elements.breakdownExistingSize) {
        elements.breakdownExistingSize.textContent = `(${formatSize(existingSizeMb * 1024 * 1024)})`;
    }
    if (elements.breakdownNewCount) {
        elements.breakdownNewCount.textContent = newCount + suspectCount;
    }
    if (elements.breakdownNewSize) {
        elements.breakdownNewSize.textContent = `(${formatSize(newSizeMb * 1024 * 1024)})`;
    }
    if (elements.breakdownRemovedCount) {
        elements.breakdownRemovedCount.textContent = removedCount;
    }

    // Show the stats card
    if (elements.playlistStatsCard) {
        elements.playlistStatsCard.classList.remove('hidden');
    }
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
    // This function is now deprecated - stats are shown in the playlist stats card
    // Keep for backward compatibility but do nothing if elements don't exist
    if (!syncPreview) {
        return;
    }
    // Storage display is updated separately via updateStorageDisplay
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

        const usedMb = storage.used_mb || 0;
        const usedGb = usedMb / 1024;
        const limitGb = storage.limit_gb || 32;
        const limitMb = limitGb * 1024;
        const percent = Math.min((usedGb / limitGb) * 100, 100);

        // Calculate after-sync values based on current sync preview
        let afterSyncMb = usedMb;
        let deltaMb = 0;
        if (syncPreview) {
            const newCount = (syncPreview.new ? syncPreview.new.length : 0) +
                             (syncPreview.suspect ? syncPreview.suspect.length : 0);
            const avgSizeMb = 8; // ~8MB per track estimate
            deltaMb = newCount * avgSizeMb;
            afterSyncMb = usedMb + deltaMb;
        }

        const afterSyncGb = afterSyncMb / 1024;
        const afterSyncPercent = Math.min((afterSyncGb / limitGb) * 100, 100);
        const remainingGb = Math.max(limitGb - afterSyncGb, 0);

        // Update storage display
        if (elements.storageUsed) {
            elements.storageUsed.textContent = `${usedGb.toFixed(1)} GB`;
        }
        if (elements.storageFill) {
            elements.storageFill.style.width = `${percent}%`;
        }
        if (elements.storageLimitLabel) {
            elements.storageLimitLabel.textContent = `${limitGb} GB`;
        }

        // Update after-sync info
        if (elements.storageAfterSync) {
            elements.storageAfterSync.textContent = `${afterSyncGb.toFixed(1)} GB`;
        }
        if (elements.storageDelta) {
            if (deltaMb > 0) {
                elements.storageDelta.textContent = `(+${formatSize(deltaMb * 1024 * 1024)})`;
            } else {
                elements.storageDelta.textContent = '';
            }
        }
        if (elements.storageRemaining) {
            elements.storageRemaining.textContent = `${remainingGb.toFixed(1)} GB`;
        }

        // Update after-sync marker on progress bar
        if (elements.storageAfterSyncMarker) {
            if (deltaMb > 0) {
                elements.storageAfterSyncMarker.style.left = `${afterSyncPercent}%`;
                elements.storageAfterSyncMarker.classList.remove('hidden');
            } else {
                elements.storageAfterSyncMarker.classList.add('hidden');
            }
        }

        // Update library stats on settings page
        if (elements.libraryTotalTracks && storage.track_count !== undefined) {
            elements.libraryTotalTracks.textContent = storage.track_count;
        }
        if (elements.librarySize) {
            elements.librarySize.textContent = formatSize(usedMb * 1024 * 1024);
        }
        if (elements.libraryAvgSize && storage.track_count > 0) {
            const avgSize = usedMb / storage.track_count;
            elements.libraryAvgSize.textContent = formatSize(avgSize * 1024 * 1024);
        }
        if (elements.libraryDeviceCapacity) {
            elements.libraryDeviceCapacity.textContent = `${limitGb} GB`;
        }
        if (elements.libraryLastSync && storage.last_sync) {
            elements.libraryLastSync.textContent = formatLastSync(storage.last_sync);
        }

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
    const current = status.current || 0;
    const total = status.total || 0;
    const percent = total > 0 ? Math.round((current / total) * 100) : 0;

    // Update percentage displays
    if (elements.syncPercent) {
        elements.syncPercent.textContent = `${percent}%`;
    }
    if (elements.syncPercentInner) {
        elements.syncPercentInner.textContent = `${percent}%`;
    }

    // Update current track name
    if (elements.syncCurrentTrack) {
        elements.syncCurrentTrack.textContent = status.current_track || 'Waiting...';
    }

    // Update track counter
    if (elements.syncCurrentNum) {
        elements.syncCurrentNum.textContent = current;
    }
    if (elements.syncTotalNum) {
        elements.syncTotalNum.textContent = total;
    }

    // Update download speed
    if (elements.syncSpeed) {
        const speedMbps = status.speed_mbps || 0;
        elements.syncSpeed.textContent = speedMbps > 0 ? `${speedMbps.toFixed(1)} MB/s` : '0 MB/s';
    }

    // Calculate and update downloaded size
    const avgSizeMb = 8; // ~8MB per track estimate
    const downloadedMb = current * avgSizeMb;
    const totalMb = total * avgSizeMb;

    if (elements.syncDownloadedSize) {
        elements.syncDownloadedSize.textContent = formatSize(downloadedMb * 1024 * 1024);
    }
    if (elements.syncTotalSize) {
        elements.syncTotalSize.textContent = formatSize(totalMb * 1024 * 1024);
    }

    // Calculate ETA
    if (elements.syncEta) {
        if (current > 0 && total > 0) {
            const remaining = total - current;
            const avgTimePerTrack = 30; // Rough estimate: 30 seconds per track
            const etaSeconds = remaining * avgTimePerTrack;
            elements.syncEta.textContent = formatTime(etaSeconds);
        } else {
            elements.syncEta.textContent = 'Calculating...';
        }
    }

    // Update progress summary counts
    const doneCount = current;
    const activeCount = status.is_syncing ? 1 : 0;
    const leftCount = Math.max(total - current - activeCount, 0);

    if (elements.syncDoneCount) {
        elements.syncDoneCount.textContent = doneCount;
    }
    if (elements.syncActiveCount) {
        elements.syncActiveCount.textContent = activeCount;
    }
    if (elements.syncLeftCount) {
        elements.syncLeftCount.textContent = leftCount;
    }

    // Update progress ring
    if (elements.progressCircle) {
        const circumference = 2 * Math.PI * 45; // radius = 45
        const offset = circumference - (percent / 100) * circumference;
        elements.progressCircle.style.strokeDashoffset = offset;
    }
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

function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    const value = bytes / Math.pow(k, i);

    // Use more precision for smaller values
    if (i >= 2) { // MB and above
        return `${value.toFixed(value >= 100 ? 0 : value >= 10 ? 1 : 1)} ${sizes[i]}`;
    }
    return `${Math.round(value)} ${sizes[i]}`;
}

function formatLastSync(timestamp) {
    if (!timestamp) return 'Never';

    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;

    // Format as date for older entries
    return date.toLocaleDateString();
}
