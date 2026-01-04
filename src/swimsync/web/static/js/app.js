/**
 * Swim Sync Web UI - Application Logic
 */

// Accessibility: Announce status updates to screen readers
function announceToScreenReader(message) {
    const announcer = document.getElementById('status-announcer');
    if (announcer) {
        announcer.textContent = message;
        // Clear after announcement to allow repeated messages
        setTimeout(() => { announcer.textContent = ''; }, 1000);
    }
}

// State
let currentPlaylist = null;
let syncPreview = null;
let isSyncing = false;
let syncPollInterval = null;
let pollErrorCount = 0;
let modalResolve = null;
let failedTracks = [];  // Track names that failed to download

// Multi-playlist state (v2)
let playlists = [];
let currentPlaylistId = null;

// Modal Functions
const modalElements = {
    overlay: null,
    title: null,
    message: null,
    icon: null,
    footer: null,
    confirmBtn: null,
    cancelBtn: null
};

function initModal() {
    modalElements.overlay = document.getElementById('modal-overlay');
    modalElements.title = document.getElementById('modal-title');
    modalElements.message = document.getElementById('modal-message');
    modalElements.icon = document.getElementById('modal-icon');
    modalElements.footer = document.getElementById('modal-footer');
    modalElements.confirmBtn = document.getElementById('modal-confirm-btn');
    modalElements.cancelBtn = document.getElementById('modal-cancel-btn');

    // Check if modal elements exist
    if (!modalElements.overlay) {
        console.error('Modal overlay element not found - modal functionality disabled');
        return;
    }

    // Close on overlay click
    modalElements.overlay.addEventListener('click', (e) => {
        if (e.target === modalElements.overlay) {
            closeModal(false);
        }
    });

    // Button handlers
    modalElements.confirmBtn.addEventListener('click', () => closeModal(true));
    modalElements.cancelBtn.addEventListener('click', () => closeModal(false));

    // ESC to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modalElements.overlay.classList.contains('hidden')) {
            closeModal(false);
        }
    });

    // Focus trap for modal (Tab cycles within modal)
    modalElements.overlay.addEventListener('keydown', (e) => {
        if (e.key !== 'Tab') return;

        const focusable = modalElements.overlay.querySelectorAll('button:not([disabled])');
        const first = focusable[0];
        const last = focusable[focusable.length - 1];

        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault();
            last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault();
            first.focus();
        }
    });
}

function getModalIcon(type) {
    const icons = {
        success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22,4 12,14.01 9,11.01"/></svg>',
        error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        warning: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
        confirm: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
    };
    return icons[type] || icons.info;
}

function showModal(type, title, message) {
    return new Promise((resolve) => {
        // Fallback to native alert if modal not available
        if (!modalElements.overlay) {
            alert(`${title}\n\n${message}`);
            resolve(true);
            return;
        }

        modalResolve = resolve;

        // Set content
        modalElements.title.textContent = title;
        modalElements.message.textContent = message;

        // Set icon
        modalElements.icon.innerHTML = getModalIcon(type);
        modalElements.icon.className = 'modal-icon modal-icon-' + type;

        // Show only OK button for alerts
        modalElements.cancelBtn.classList.add('hidden');
        modalElements.confirmBtn.textContent = 'OK';

        // Show modal
        modalElements.overlay.classList.remove('hidden');
        modalElements.confirmBtn.focus();
    });
}

function showConfirm(title, message) {
    return new Promise((resolve) => {
        // Fallback to native confirm if modal not available
        if (!modalElements.overlay) {
            resolve(confirm(`${title}\n\n${message}`));
            return;
        }

        modalResolve = resolve;

        // Set content
        modalElements.title.textContent = title;
        modalElements.message.textContent = message;

        // Set icon
        modalElements.icon.innerHTML = getModalIcon('confirm');
        modalElements.icon.className = 'modal-icon modal-icon-warning';

        // Show both buttons for confirms
        modalElements.cancelBtn.classList.remove('hidden');
        modalElements.confirmBtn.textContent = 'Confirm';
        modalElements.cancelBtn.textContent = 'Cancel';

        // Show modal
        modalElements.overlay.classList.remove('hidden');
        modalElements.confirmBtn.focus();
    });
}

function closeModal(result) {
    if (modalElements.overlay) {
        modalElements.overlay.classList.add('hidden');
    }
    if (modalResolve) {
        modalResolve(result);
        modalResolve = null;
    }
}

// DOM Elements
const elements = {
    // Navigation
    navItems: document.querySelectorAll('.nav-item'),
    views: document.querySelectorAll('.view'),

    // Dashboard
    playlistUrl: document.getElementById('playlist-url'),
    loadBtn: document.getElementById('load-btn'),
    outputFolder: document.getElementById('output-folder'),
    openFolderBtn: document.getElementById('open-folder-btn'),

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
    breakdownNewItem: document.getElementById('breakdown-new-item'),
    breakdownFailedCount: document.getElementById('breakdown-failed-count'),
    breakdownFailedItem: document.getElementById('breakdown-failed-item'),
    breakdownRemovedCount: document.getElementById('breakdown-removed-count'),
    breakdownRemovedItem: document.getElementById('breakdown-removed-item'),
    syncStatusText: document.getElementById('sync-status-text'),

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
    libraryDeviceCapacity: document.getElementById('library-device-capacity'),

    // Playlist sidebar
    playlistList: document.getElementById('playlist-list'),
    addPlaylistBtn: document.getElementById('add-playlist-btn'),

    // Save to library button
    savePlaylistBtn: document.getElementById('save-playlist-btn'),

    // New UX elements
    welcomeState: document.getElementById('welcome-state'),
    libraryOverview: document.getElementById('library-overview'),
    playlistDetail: document.getElementById('playlist-detail'),
    welcomeAddBtn: document.getElementById('welcome-add-btn'),
    overviewAddBtn: document.getElementById('overview-add-btn'),
    libraryPlaylistGrid: document.getElementById('library-playlist-grid'),
    overviewPlaylistCount: document.getElementById('overview-playlist-count'),
    overviewTrackCount: document.getElementById('overview-track-count'),
    overviewStorageUsed: document.getElementById('overview-storage-used'),

    // Playlist detail header
    playlistDetailName: document.getElementById('playlist-detail-name'),
    playlistDetailUrl: document.getElementById('playlist-detail-url'),
    playlistDetailColor: document.getElementById('playlist-detail-color'),
    deletePlaylistBtn: document.getElementById('delete-playlist-btn'),

    // Track queue during sync
    syncTrackQueueList: document.getElementById('sync-track-queue-list'),

    // Sync confirm modal
    syncConfirmOverlay: document.getElementById('sync-confirm-overlay'),
    syncConfirmCancel: document.getElementById('sync-confirm-cancel'),
    syncConfirmStart: document.getElementById('sync-confirm-start'),
    syncNewCount: document.getElementById('sync-new-count'),
    syncNewCount2: document.getElementById('sync-new-count-2'),
    syncRemovedCount: document.getElementById('sync-removed-count'),
    syncSummaryNew: document.getElementById('sync-summary-new'),
    syncSummaryRemoved: document.getElementById('sync-summary-removed'),
    syncSummaryRemovedRow: document.getElementById('sync-summary-removed-row'),
    syncSummaryDownloadSize: document.getElementById('sync-summary-download-size'),
    syncModeRadios: document.querySelectorAll('input[name="sync-mode"]'),

    // Wizard elements
    wizardOverlay: document.getElementById('wizard-overlay'),
    wizardCloseBtn: document.getElementById('wizard-close-btn'),
    wizardBackBtn: document.getElementById('wizard-back-btn'),
    wizardNextBtn: document.getElementById('wizard-next-btn'),
    wizardUrl: document.getElementById('wizard-url'),
    wizardName: document.getElementById('wizard-name'),
    wizardPlaylistName: document.getElementById('wizard-playlist-name'),
    wizardPlaylistTracks: document.getElementById('wizard-playlist-tracks'),
    wizardSummaryName: document.getElementById('wizard-summary-name'),
    wizardSummaryTracks: document.getElementById('wizard-summary-tracks'),
    wizardSummarySize: document.getElementById('wizard-summary-size'),
    wizardDownloadNow: document.getElementById('wizard-download-now'),
    wizardSteps: document.querySelectorAll('.wizard-step'),
    wizardContents: document.querySelectorAll('.wizard-content'),
    wizardColorBtns: document.querySelectorAll('.wizard-color-btn')
};

// Wizard state
let wizardStep = 1;
let wizardData = {
    url: '',
    name: '',
    color: '#22c55e',
    tracks: 0,
    playlistInfo: null
};

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    initModal();
    setupEventListeners();
    setupWizard();

    // Sync button starts disabled until playlist is loaded from Spotify
    if (elements.syncBtn) {
        elements.syncBtn.disabled = true;
    }

    await loadConfig();
    await loadPlaylists();
    await updateStorageDisplay();
    determineInitialView();

    // If we have a current playlist, reload its data from Spotify
    if (currentPlaylistId) {
        const playlist = playlists.find(p => p.id === currentPlaylistId);
        if (playlist) {
            updatePlaylistDetailHeader(playlist);
            // Load playlist from Spotify if URL is set
            if (playlist.spotify_url) {
                elements.playlistUrl.value = playlist.spotify_url;
                await loadPlaylist();
            }
        }
    }
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

    // Open folder in file explorer
    if (elements.openFolderBtn) {
        elements.openFolderBtn.addEventListener('click', openPlaylistFolder);
    }

    // Sync actions
    elements.syncBtn.addEventListener('click', showSyncConfirmModal);
    elements.cancelBtn.addEventListener('click', cancelSync);

    // Sync confirm modal
    setupSyncConfirmModal();

    // Settings
    elements.saveSettingsBtn.addEventListener('click', saveSettings);

    // Playlist sidebar
    if (elements.addPlaylistBtn) {
        elements.addPlaylistBtn.addEventListener('click', openWizard);
    }

    // Save to library button
    if (elements.savePlaylistBtn) {
        elements.savePlaylistBtn.addEventListener('click', savePlaylistToLibrary);
    }

    // Welcome/Overview add buttons
    if (elements.welcomeAddBtn) {
        elements.welcomeAddBtn.addEventListener('click', openWizard);
    }
    if (elements.overviewAddBtn) {
        elements.overviewAddBtn.addEventListener('click', openWizard);
    }

    // Delete playlist button
    if (elements.deletePlaylistBtn) {
        elements.deletePlaylistBtn.addEventListener('click', handleDeleteCurrentPlaylist);
    }

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
        const isActive = item.dataset.view === viewName;
        item.classList.toggle('active', isActive);
        if (isActive) {
            item.setAttribute('aria-current', 'page');
        } else {
            item.removeAttribute('aria-current');
        }
    });

    // Update views
    elements.views.forEach(view => {
        view.classList.toggle('active', view.id === `${viewName}-view`);
        view.classList.toggle('hidden', view.id !== `${viewName}-view`);
    });

    // When switching to dashboard, determine appropriate sub-view
    if (viewName === 'dashboard') {
        determineInitialView();
    }
}

// API Functions
async function loadConfig() {
    try {
        const response = await fetch('/api/config');
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Configuration Error', `Failed to load configuration: ${data.error || response.statusText}`);
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
        await showModal('error', 'Configuration Error', `Failed to load configuration: ${error.message}`);
    }
}

async function openPlaylistFolder() {
    if (!currentPlaylistId) {
        await showModal('info', 'No Playlist Selected', 'Please select or create a playlist first.');
        return;
    }

    try {
        const response = await fetch(`/api/playlists/${currentPlaylistId}/open-folder`, {
            method: 'POST'
        });

        if (!response.ok) {
            const data = await response.json();
            await showModal('error', 'Error', data.error || 'Failed to open folder');
        }
    } catch (error) {
        await showModal('error', 'Error', 'Failed to open folder: ' + error.message);
    }
}

async function loadPlaylist() {
    const url = elements.playlistUrl.value.trim();

    if (!url) {
        await showModal('warning', 'Missing URL', 'Please enter a Spotify playlist URL');
        return;
    }

    if (!url.includes('open.spotify.com/playlist')) {
        await showModal('warning', 'Invalid URL', 'Please enter a valid Spotify playlist URL');
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

        // Refresh sidebar counts (stats may have been updated by manifest sync)
        await loadPlaylists();

    } catch (error) {
        await showModal('error', 'Load Failed', error.message);
        elements.emptyState.classList.remove('hidden');
    } finally {
        elements.loadingState.classList.add('hidden');
        elements.loadBtn.disabled = false;
    }
}

function displayPlaylist(data) {
    elements.playlistName.textContent = data.playlist_name;
    elements.trackCount.textContent = `${data.tracks.length} tracks`;

    // Update folder path to show playlist-specific folder
    if (elements.outputFolder && data.playlist_folder) {
        elements.outputFolder.value = data.playlist_folder;
    }

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

        // Check if this track failed to download (track name format: "title - artist")
        const trackKey = `${track.title} - ${track.artist}`;
        const isFailed = failedTracks.some(failedName =>
            failedName.includes(track.title) || trackKey.includes(failedName.split(' - ')[0])
        );
        const displayStatus = (isFailed && track.status === 'new') ? 'failed' : track.status;

        const titleCell = document.createElement('td');
        titleCell.textContent = track.title;
        row.appendChild(titleCell);

        const artistCell = document.createElement('td');
        artistCell.textContent = track.artist;
        row.appendChild(artistCell);

        const statusCell = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = `status-badge status-${displayStatus}`;
        badge.textContent = getStatusLabel(displayStatus);
        statusCell.appendChild(badge);
        row.appendChild(statusCell);

        elements.trackList.appendChild(row);
    });

    elements.trackListContainer.classList.remove('hidden');

    // Update playlist stats card
    updatePlaylistStats(data);

    // Update button states and text based on whether this playlist is in library
    const url = elements.playlistUrl.value.trim();
    const inLibrary = isPlaylistInLibrary(url);
    const newCount = data.preview.new.length + data.preview.suspect.length;
    const removedCount = data.preview.removed.length;

    if (elements.savePlaylistBtn) {
        if (inLibrary) {
            elements.savePlaylistBtn.classList.add('hidden');
        } else {
            elements.savePlaylistBtn.classList.remove('hidden');
        }
    }

    // Update Load/Refresh button text
    if (elements.loadBtn) {
        if (inLibrary) {
            elements.loadBtn.textContent = 'Check for Updates';
        } else {
            elements.loadBtn.textContent = 'Load Playlist';
        }
    }

    // Update Sync button text with count
    if (elements.syncBtn) {
        if (newCount > 0) {
            elements.syncBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                Download ${newCount} Track${newCount !== 1 ? 's' : ''}
            `;
        } else if (removedCount > 0) {
            elements.syncBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <polyline points="23 4 23 10 17 10"/>
                    <polyline points="1 20 1 14 7 14"/>
                    <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
                </svg>
                Sync Changes
            `;
        } else {
            elements.syncBtn.innerHTML = `
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                    <polyline points="22 4 12 14.01 9 11.01"/>
                </svg>
                Up to Date
            `;
        }
    }

    // Enable sync button if there's work to do
    const hasWork = newCount > 0 ||
                    (removedCount > 0 && elements.deleteRemovedToggle.checked);
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

    // Count failed tracks from the failedTracks array
    const failedTrackCount = failedTracks.length;

    // Calculate actual new count (excluding failed tracks)
    const actualNewCount = Math.max((newCount + suspectCount) - failedTrackCount, 0);

    // Update breakdown
    if (elements.breakdownExistingCount) {
        elements.breakdownExistingCount.textContent = existingCount;
    }
    if (elements.breakdownExistingSize) {
        elements.breakdownExistingSize.textContent = `(${formatSize(existingSizeMb * 1024 * 1024)})`;
    }

    // Show/hide new vs failed breakdown items
    if (elements.breakdownNewItem) {
        if (actualNewCount > 0) {
            elements.breakdownNewItem.classList.remove('hidden');
            if (elements.breakdownNewCount) {
                elements.breakdownNewCount.textContent = actualNewCount;
            }
            if (elements.breakdownNewSize) {
                const actualNewSizeMb = actualNewCount * avgSizeMb;
                elements.breakdownNewSize.textContent = `(${formatSize(actualNewSizeMb * 1024 * 1024)})`;
            }
        } else {
            elements.breakdownNewItem.classList.add('hidden');
        }
    }

    if (elements.breakdownFailedItem) {
        if (failedTrackCount > 0) {
            elements.breakdownFailedItem.classList.remove('hidden');
            if (elements.breakdownFailedCount) {
                elements.breakdownFailedCount.textContent = failedTrackCount;
            }
        } else {
            elements.breakdownFailedItem.classList.add('hidden');
        }
    }

    if (elements.breakdownRemovedCount) {
        elements.breakdownRemovedCount.textContent = removedCount;
    }

    // Show/hide removed item based on count
    if (elements.breakdownRemovedItem) {
        if (removedCount > 0) {
            elements.breakdownRemovedItem.classList.remove('hidden');
        } else {
            elements.breakdownRemovedItem.classList.add('hidden');
        }
    }

    // Generate natural language summary
    if (elements.syncStatusText) {
        let summary = '';
        const libraryTotal = existingCount + removedCount;

        if (existingCount === totalTracks && actualNewCount === 0) {
            // Fully synced
            summary = `<strong>All ${totalTracks} tracks</strong> are downloaded and ready to sync to your device.`;
        } else if (existingCount === 0 && actualNewCount === totalTracks) {
            // New playlist, nothing downloaded
            summary = `This playlist has <strong>${totalTracks} tracks</strong>. Download them to add to your library.`;
        } else if (actualNewCount > 0) {
            // Partially synced, has new tracks
            summary = `You have <strong>${existingCount} of ${totalTracks}</strong> Spotify tracks. `;
            summary += `<span class="highlight-new">${actualNewCount} new</span> to download.`;
        } else {
            // All tracks exist
            summary = `You have <strong>${existingCount} of ${totalTracks}</strong> Spotify tracks downloaded.`;
        }

        // Add library context if there are removed tracks (explains sidebar count)
        if (removedCount > 0) {
            summary += `<br><span class="highlight-removed">Your library has <strong>${libraryTotal}</strong> tracks total — ${removedCount} are no longer on this Spotify playlist.</span>`;
        }

        elements.syncStatusText.innerHTML = summary;
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
        'suspect': 'Suspect',
        'failed': 'Failed'
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
                await showModal('error', 'Storage Error', `Failed to load storage info: ${data.error || response.statusText}`);
                return;
            }
            storage = await response.json();
        }

        const usedMb = storage.used_mb || 0;
        const usedGb = usedMb / 1024;
        const limitGb = storage.limit_gb || 32;
        const limitMb = limitGb * 1024;
        const percent = Math.min((usedGb / limitGb) * 100, 100);

        // Calculate after-sync values based on current sync preview (excluding failed tracks)
        let afterSyncMb = usedMb;
        let deltaMb = 0;
        if (syncPreview) {
            const newCount = (syncPreview.new ? syncPreview.new.length : 0) +
                             (syncPreview.suspect ? syncPreview.suspect.length : 0);
            // Subtract failed tracks from the estimate
            const actualNewCount = Math.max(newCount - failedTracks.length, 0);
            const avgSizeMb = 8; // ~8MB per track estimate
            deltaMb = actualNewCount * avgSizeMb;
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
        await showModal('error', 'Storage Error', `Failed to load storage info: ${error.message}`);
    }
}

async function startSync() {
    if (!syncPreview || isSyncing) return;

    const deleteRemoved = elements.deleteRemovedToggle.checked;

    // Confirm deletion
    if (deleteRemoved && syncPreview.removed.length > 0) {
        const confirmed = await showConfirm('Confirm Deletion', `This will delete ${syncPreview.removed.length} track(s) that were removed from the playlist. Continue?`);
        if (!confirmed) {
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
        await showModal('error', 'Sync Failed', error.message);
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
                showModal('error', 'Connection Lost', 'Lost connection to server');
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

            resetSyncState();
            await updateStorageDisplay();

            if (status.status === 'completed') {
                // Store failed tracks for display
                failedTracks = status.failed_tracks || [];

                // Refresh playlist first to update track statuses
                if (elements.playlistUrl.value.trim()) {
                    await loadPlaylist();
                }

                // Show appropriate message based on failed downloads
                const failedCount = status.failed_count || 0;
                const completedCount = status.completed_count || 0;

                if (failedCount > 0 && completedCount === 0) {
                    announceToScreenReader(`Download failed. All ${failedCount} tracks failed.`);
                    await showModal('error', 'Sync Failed', `All ${failedCount} download(s) failed. The tracks may not be available.`);
                } else if (failedCount > 0) {
                    announceToScreenReader(`Download complete. ${completedCount} tracks downloaded, ${failedCount} failed.`);
                    await showModal('warning', 'Sync Completed with Errors', `${completedCount} track(s) downloaded, ${failedCount} failed. Some tracks may not be available on YouTube.`);
                } else {
                    announceToScreenReader('Download complete. All tracks downloaded successfully.');
                    await showModal('success', 'Sync Complete', 'Sync completed successfully!');
                }
            } else if (status.status === 'error') {
                showModal('error', 'Sync Failed', status.error);
            } else if (status.status === 'cancelled') {
                showModal('info', 'Sync Cancelled', 'Sync was cancelled');
            }
        }

    } catch (error) {
        pollErrorCount++;
        console.error(`Failed to poll sync status (attempt ${pollErrorCount}):`, error);
        if (pollErrorCount >= 3) {
            clearInterval(syncPollInterval);
            showModal('error', 'Connection Lost', 'Lost connection to server');
            resetSyncState();
        }
    }
}

function updateSyncProgress(status) {
    const current = status.current || 0;
    const total = status.total || 0;
    const completed = (status.completed_count || 0) + (status.failed_count || 0);

    // Calculate percent based on completed tracks, not current track being processed
    // This prevents showing 100% while a track is still downloading
    const percent = total > 0 ? Math.round((completed / total) * 100) : 0;

    // Determine display text based on status
    const isDownloading = status.status === 'Downloading';
    const displayText = `${percent}%`;

    // Update percentage displays
    if (elements.syncPercent) {
        elements.syncPercent.textContent = displayText;
    }
    if (elements.syncPercentInner) {
        elements.syncPercentInner.textContent = displayText;
    }

    // Update current track name with status indicator
    if (elements.syncCurrentTrack) {
        if (isDownloading && status.current_track) {
            elements.syncCurrentTrack.textContent = `⏳ ${status.current_track}`;
        } else {
            elements.syncCurrentTrack.textContent = status.current_track || 'Waiting...';
        }
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

    // Calculate and update downloaded size (use completed count, not current)
    const avgSizeMb = 8; // ~8MB per track estimate
    const downloadedMb = completed * avgSizeMb;
    const totalMb = total * avgSizeMb;

    if (elements.syncDownloadedSize) {
        elements.syncDownloadedSize.textContent = formatSize(downloadedMb * 1024 * 1024);
    }
    if (elements.syncTotalSize) {
        elements.syncTotalSize.textContent = formatSize(totalMb * 1024 * 1024);
    }

    // Calculate ETA based on remaining tracks
    if (elements.syncEta) {
        const remaining = total - completed;
        if (remaining > 0) {
            const avgTimePerTrack = 30; // Rough estimate: 30 seconds per track
            const etaSeconds = remaining * avgTimePerTrack;
            elements.syncEta.textContent = formatTime(etaSeconds);
        } else {
            elements.syncEta.textContent = '~0s';
        }
    }

    // Update progress summary counts using actual completed/failed counts
    const doneCount = status.completed_count || 0;
    const failedCount = status.failed_count || 0;
    const activeCount = isDownloading ? 1 : 0;
    const leftCount = Math.max(total - completed - activeCount, 0);

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

    // Update live track queue
    if (elements.syncTrackQueueList && status.track_queue) {
        renderTrackQueue(status.track_queue);
    }

    // Update sidebar count live during sync
    if (currentPlaylistId && status.completed_count > 0) {
        updateSidebarCountLive(status.completed_count);
    }
}

function renderTrackQueue(trackQueue) {
    if (!elements.syncTrackQueueList) return;

    // Sort: downloading first, then pending, then completed/failed at bottom
    const sortOrder = { downloading: 0, pending: 1, downloaded: 2, failed: 2 };
    const sortedQueue = [...trackQueue].sort((a, b) => {
        return (sortOrder[a.status] || 1) - (sortOrder[b.status] || 1);
    });

    // Build HTML for track items
    const html = sortedQueue.map(track => {
        const statusClass = `track-status-${track.status}`;
        const statusIcon = getTrackStatusIcon(track.status);
        const sizeText = track.status === 'downloaded' && track.file_size_mb > 0
            ? `<span class="track-size">${track.file_size_mb.toFixed(1)} MB</span>`
            : '';

        return `
            <div class="sync-track-item ${statusClass}">
                <span class="sync-track-status">${statusIcon}</span>
                <div class="sync-track-info">
                    <span class="sync-track-title">${escapeHtml(track.title)}</span>
                    <span class="sync-track-artist">${escapeHtml(track.artist)}</span>
                </div>
                ${sizeText}
            </div>
        `;
    }).join('');

    elements.syncTrackQueueList.innerHTML = html;

    // Scroll to keep downloading track visible
    const downloadingItem = elements.syncTrackQueueList.querySelector('.track-status-downloading');
    if (downloadingItem) {
        downloadingItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
}

function getTrackStatusIcon(status) {
    switch (status) {
        case 'downloading':
            return '<span class="status-spinner">⏳</span>';
        case 'downloaded':
            return '<span class="status-done">✓</span>';
        case 'failed':
            return '<span class="status-failed">✗</span>';
        case 'pending':
        default:
            return '<span class="status-pending">○</span>';
    }
}

function updateSidebarCountLive(completedCount) {
    // Find current playlist in sidebar and update count
    const playlistItem = document.querySelector(`.playlist-nav-item[data-playlist-id="${currentPlaylistId}"]`);
    if (playlistItem) {
        const countEl = playlistItem.querySelector('.playlist-nav-item-count');
        if (countEl) {
            // Get existing count and add completed downloads
            const existingCount = syncPreview?.existing?.length || 0;
            countEl.textContent = existingCount + completedCount;
        }
    }
}

async function cancelSync() {
    if (!isSyncing) return;

    try {
        const response = await fetch('/api/sync/cancel', { method: 'POST' });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Cancel Failed', `Failed to cancel sync: ${data.error || response.statusText}`);
        }
    } catch (error) {
        console.error('Failed to cancel sync:', error);
        await showModal('error', 'Cancel Failed', `Failed to cancel sync: ${error.message}`);
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
            await showModal('success', 'Settings Saved', 'Settings saved successfully!');
            await updateStorageDisplay();
        } else {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Save Failed', `Failed to save settings: ${data.error || response.statusText}`);
        }

    } catch (error) {
        await showModal('error', 'Save Failed', error.message);
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

    // Use more precision for larger units (MB and above)
    if (i >= 2) {
        const decimals = value >= 100 ? 0 : 1;
        return `${value.toFixed(decimals)} ${sizes[i]}`;
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

// Playlist Management Functions (v2)
async function loadPlaylists() {
    try {
        const response = await fetch('/api/playlists');
        if (!response.ok) {
            // Silently fail if endpoint doesn't exist (v1 mode)
            console.log('Playlists endpoint not available (v1 mode)');
            return;
        }

        const data = await response.json();
        playlists = data.playlists || [];
        currentPlaylistId = data.current_playlist_id || null;

        renderPlaylistNav();
    } catch (error) {
        console.log('Failed to load playlists:', error.message);
    }
}

function renderPlaylistNav() {
    if (!elements.playlistList) return;

    // Clear existing items
    while (elements.playlistList.firstChild) {
        elements.playlistList.removeChild(elements.playlistList.firstChild);
    }

    if (playlists.length === 0) {
        const emptyMsg = document.createElement('div');
        emptyMsg.className = 'playlist-nav-empty';
        emptyMsg.textContent = 'No playlists yet';
        elements.playlistList.appendChild(emptyMsg);
        return;
    }

    playlists.forEach(playlist => {
        const item = document.createElement('div');
        item.className = 'playlist-nav-item';
        if (playlist.id === currentPlaylistId) {
            item.classList.add('active');
        }
        item.dataset.playlistId = playlist.id;  // becomes data-playlist-id in HTML

        // Color dot
        const dot = document.createElement('span');
        dot.className = 'playlist-color-dot';
        dot.style.backgroundColor = playlist.color || '#3b82f6';
        item.appendChild(dot);

        // Playlist name
        const name = document.createElement('span');
        name.className = 'playlist-nav-item-name';
        name.textContent = playlist.name;
        item.appendChild(name);

        // Track count badge
        const count = document.createElement('span');
        count.className = 'playlist-nav-item-count';
        count.textContent = playlist.track_count || 0;
        count.title = 'Tracks in your library';
        item.appendChild(count);

        // Click handler
        item.addEventListener('click', () => selectPlaylist(playlist.id));

        elements.playlistList.appendChild(item);
    });
}

async function selectPlaylist(playlistId) {
    try {
        // Disable sync button until playlist is loaded from Spotify
        if (elements.syncBtn) {
            elements.syncBtn.disabled = true;
        }
        syncPreview = null;

        const response = await fetch(`/api/playlists/${playlistId}/select`, {
            method: 'POST'
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Select Failed', data.error || 'Failed to select playlist');
            return;
        }

        const data = await response.json();
        currentPlaylistId = playlistId;

        // Show playlist detail view
        showPlaylistDetail();

        // Update playlist detail header
        const playlist = playlists.find(p => p.id === playlistId);
        if (playlist) {
            updatePlaylistDetailHeader(playlist);
        }

        // Update nav highlighting
        renderPlaylistNav();

        // Load playlist URL into input and trigger load
        if (playlist && playlist.spotify_url) {
            elements.playlistUrl.value = playlist.spotify_url;
            await loadPlaylist();
        } else {
            // No Spotify URL - show message to load playlist
            if (elements.syncStatusText) {
                elements.syncStatusText.innerHTML = 'Click <strong>Load Playlist</strong> to fetch tracks from Spotify.';
            }
        }

        // Update storage display
        await updateStorageDisplay();

    } catch (error) {
        await showModal('error', 'Select Failed', error.message);
    }
}

function updatePlaylistDetailHeader(playlist) {
    if (elements.playlistDetailName) {
        elements.playlistDetailName.textContent = playlist.name;
    }
    if (elements.playlistDetailUrl) {
        // Show shortened URL
        const url = playlist.spotify_url || '';
        const shortUrl = url.replace('https://open.spotify.com/playlist/', '').split('?')[0];
        elements.playlistDetailUrl.textContent = shortUrl ? `spotify:playlist:${shortUrl.substring(0, 22)}` : 'No Spotify URL';
    }
    if (elements.playlistDetailColor) {
        elements.playlistDetailColor.style.background = playlist.color || '#3b82f6';
    }
}

async function handleDeleteCurrentPlaylist() {
    if (!currentPlaylistId) {
        await showModal('warning', 'No Playlist Selected', 'Please select a playlist first');
        return;
    }

    const playlist = playlists.find(p => p.id === currentPlaylistId);
    if (!playlist) return;

    const confirmed = await showConfirm(
        'Delete Playlist',
        `Are you sure you want to delete "${playlist.name}"?\n\nThis will remove the playlist from your library. Downloaded tracks that are only used by this playlist will also be deleted.`
    );

    if (!confirmed) return;

    try {
        const response = await fetch(`/api/playlists/${currentPlaylistId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Delete Failed', data.error || 'Failed to delete playlist');
            return;
        }

        announceToScreenReader(`Playlist "${playlist.name}" deleted`);

        // Reset current playlist
        currentPlaylistId = null;
        currentPlaylist = null;
        syncPreview = null;

        // Reload playlists
        await loadPlaylists();

        // Show appropriate view
        determineInitialView();

        await showModal('success', 'Playlist Deleted', `"${playlist.name}" has been removed from your library`);

    } catch (error) {
        await showModal('error', 'Delete Failed', error.message);
    }
}

async function createPlaylist() {
    // Simple prompt for now - could be replaced with a modal form
    const name = prompt('Enter playlist name:');
    if (!name || !name.trim()) return;

    const url = prompt('Enter Spotify playlist URL (optional):');

    try {
        const response = await fetch('/api/playlists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name.trim(),
                spotify_url: url ? url.trim() : ''
            })
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Create Failed', data.error || 'Failed to create playlist');
            return;
        }

        const data = await response.json();
        await showModal('success', 'Playlist Created', `Created playlist "${data.name}"`);

        // Reload playlists
        await loadPlaylists();

        // Select the new playlist
        if (data.id) {
            await selectPlaylist(data.id);
        }

    } catch (error) {
        await showModal('error', 'Create Failed', error.message);
    }
}

async function savePlaylistToLibrary() {
    if (!currentPlaylist) {
        await showModal('warning', 'No Playlist', 'Load a playlist first');
        return;
    }

    const url = elements.playlistUrl.value.trim();
    const name = currentPlaylist.playlist_name || 'Untitled Playlist';

    try {
        const response = await fetch('/api/playlists', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                spotify_url: url
            })
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Save Failed', data.error || 'Failed to save playlist');
            return;
        }

        const data = await response.json();

        // Hide save button, reload playlists, select the new one
        if (elements.savePlaylistBtn) {
            elements.savePlaylistBtn.classList.add('hidden');
        }

        await loadPlaylists();

        if (data.id) {
            await selectPlaylist(data.id);
        }

        await showModal('success', 'Playlist Saved', `"${name}" has been added to your library`);

    } catch (error) {
        await showModal('error', 'Save Failed', error.message);
    }
}

function isPlaylistInLibrary(spotifyUrl) {
    // Check if this Spotify URL is already in our library
    if (!spotifyUrl || !playlists.length) return false;
    return playlists.some(p => p.spotify_url && p.spotify_url.includes(spotifyUrl.split('?')[0]));
}

async function deletePlaylist(playlistId) {
    const playlist = playlists.find(p => p.id === playlistId);
    if (!playlist) return;

    const confirmed = await showConfirm(
        'Delete Playlist',
        `Delete "${playlist.name}"? This will remove the playlist but keep the tracks in storage.`
    );

    if (!confirmed) return;

    try {
        const response = await fetch(`/api/playlists/${playlistId}`, {
            method: 'DELETE'
        });

        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            await showModal('error', 'Delete Failed', data.error || 'Failed to delete playlist');
            return;
        }

        await showModal('success', 'Playlist Deleted', `Deleted "${playlist.name}"`);

        // Reload playlists
        await loadPlaylists();

    } catch (error) {
        await showModal('error', 'Delete Failed', error.message);
    }
}

// ==================== SMART VIEW ROUTING ====================

function determineInitialView() {
    // Smart routing: determine which view to show on app launch
    if (playlists.length === 0) {
        // New user - show welcome screen
        showWelcomeState();
    } else if (currentPlaylistId) {
        // Has a selected playlist - show playlist detail
        showPlaylistDetail();
    } else {
        // Has playlists but none selected - show library overview
        showLibraryOverview();
    }
}

function showWelcomeState() {
    hideAllDashboardStates();
    if (elements.welcomeState) {
        elements.welcomeState.classList.remove('hidden');
    }
}

function showLibraryOverview() {
    hideAllDashboardStates();
    if (elements.libraryOverview) {
        elements.libraryOverview.classList.remove('hidden');
        renderLibraryOverview();
    }
}

function showPlaylistDetail() {
    hideAllDashboardStates();
    if (elements.playlistDetail) {
        elements.playlistDetail.classList.remove('hidden');
    }
}

function hideAllDashboardStates() {
    if (elements.welcomeState) elements.welcomeState.classList.add('hidden');
    if (elements.libraryOverview) elements.libraryOverview.classList.add('hidden');
    if (elements.playlistDetail) elements.playlistDetail.classList.add('hidden');
}

function renderLibraryOverview() {
    // Update stats
    const totalTracks = playlists.reduce((sum, p) => sum + (p.track_count || 0), 0);

    if (elements.overviewPlaylistCount) {
        elements.overviewPlaylistCount.textContent = playlists.length;
    }
    if (elements.overviewTrackCount) {
        elements.overviewTrackCount.textContent = totalTracks;
    }

    // Render playlist cards
    if (elements.libraryPlaylistGrid) {
        while (elements.libraryPlaylistGrid.firstChild) {
            elements.libraryPlaylistGrid.removeChild(elements.libraryPlaylistGrid.firstChild);
        }

        playlists.forEach(playlist => {
            const card = createPlaylistCard(playlist);
            elements.libraryPlaylistGrid.appendChild(card);
        });
    }
}

function createPlaylistCard(playlist) {
    const card = document.createElement('div');
    card.className = 'playlist-card';
    card.style.setProperty('--card-color', playlist.color || '#3b82f6');
    card.dataset.playlistId = playlist.id;

    card.innerHTML = `
        <div class="playlist-card-header">
            <div class="playlist-card-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M9 18V5l12-2v13"/>
                    <circle cx="6" cy="18" r="3"/>
                    <circle cx="18" cy="16" r="3"/>
                </svg>
            </div>
            <div class="playlist-card-info">
                <span class="playlist-card-name">${escapeHtml(playlist.name)}</span>
                <span class="playlist-card-tracks">${playlist.track_count || 0} tracks</span>
            </div>
        </div>
        <div class="playlist-card-status">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
                <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <span>Synced</span>
        </div>
    `;

    card.addEventListener('click', () => selectPlaylist(playlist.id));

    return card;
}

// ==================== WIZARD FUNCTIONS ====================

function setupWizard() {
    if (!elements.wizardOverlay) return;

    // Close button
    if (elements.wizardCloseBtn) {
        elements.wizardCloseBtn.addEventListener('click', closeWizard);
    }

    // Overlay click to close
    elements.wizardOverlay.addEventListener('click', (e) => {
        if (e.target === elements.wizardOverlay) {
            closeWizard();
        }
    });

    // Back button
    if (elements.wizardBackBtn) {
        elements.wizardBackBtn.addEventListener('click', wizardBack);
    }

    // Next/Continue button
    if (elements.wizardNextBtn) {
        elements.wizardNextBtn.addEventListener('click', wizardNext);
    }

    // Color picker buttons
    elements.wizardColorBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            elements.wizardColorBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            wizardData.color = btn.dataset.color;
        });
    });

    // ESC to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !elements.wizardOverlay.classList.contains('hidden')) {
            closeWizard();
        }
    });
}

function openWizard() {
    // Reset wizard state
    wizardStep = 1;
    wizardData = {
        url: '',
        name: '',
        color: '#22c55e',
        tracks: 0,
        playlistInfo: null
    };

    // Reset form fields
    if (elements.wizardUrl) elements.wizardUrl.value = '';
    if (elements.wizardName) elements.wizardName.value = '';

    // Reset color selection
    elements.wizardColorBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.color === '#22c55e');
    });

    // Show step 1
    updateWizardStep();

    // Show wizard
    elements.wizardOverlay.classList.remove('hidden');
    if (elements.wizardUrl) elements.wizardUrl.focus();
}

function closeWizard() {
    elements.wizardOverlay.classList.add('hidden');
}

function updateWizardStep() {
    // Update step indicators
    elements.wizardSteps.forEach((step, index) => {
        const stepNum = index + 1;
        step.classList.remove('active', 'completed');
        if (stepNum === wizardStep) {
            step.classList.add('active');
        } else if (stepNum < wizardStep) {
            step.classList.add('completed');
        }
    });

    // Show/hide content
    elements.wizardContents.forEach((content, index) => {
        content.classList.toggle('hidden', index + 1 !== wizardStep);
    });

    // Update buttons
    if (elements.wizardBackBtn) {
        elements.wizardBackBtn.classList.toggle('hidden', wizardStep === 1);
    }
    if (elements.wizardNextBtn) {
        elements.wizardNextBtn.textContent = wizardStep === 3 ? 'Add Playlist' : 'Continue';
    }
}

function wizardBack() {
    if (wizardStep > 1) {
        wizardStep--;
        updateWizardStep();
    }
}

async function wizardNext() {
    if (wizardStep === 1) {
        // Validate URL and fetch playlist info
        const url = elements.wizardUrl ? elements.wizardUrl.value.trim() : '';

        if (!url) {
            await showModal('warning', 'Missing URL', 'Please enter a Spotify playlist URL');
            return;
        }

        if (!url.includes('open.spotify.com/playlist')) {
            await showModal('warning', 'Invalid URL', 'Please enter a valid Spotify playlist URL');
            return;
        }

        wizardData.url = url;

        // Show loading state
        elements.wizardNextBtn.disabled = true;
        elements.wizardNextBtn.textContent = 'Loading...';

        try {
            // Fetch playlist info
            const response = await fetch('/api/playlist/load', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || 'Failed to load playlist');
            }

            wizardData.playlistInfo = data;
            wizardData.name = data.playlist_name;
            wizardData.tracks = data.tracks.length;

            // Update step 2 preview
            if (elements.wizardPlaylistName) {
                elements.wizardPlaylistName.textContent = data.playlist_name;
            }
            if (elements.wizardPlaylistTracks) {
                elements.wizardPlaylistTracks.textContent = `${data.tracks.length} tracks`;
            }
            if (elements.wizardName) {
                elements.wizardName.placeholder = data.playlist_name;
            }

            wizardStep = 2;
            updateWizardStep();

        } catch (error) {
            await showModal('error', 'Load Failed', error.message);
        } finally {
            elements.wizardNextBtn.disabled = false;
            elements.wizardNextBtn.textContent = 'Continue';
        }

    } else if (wizardStep === 2) {
        // Get custom name if provided
        const customName = elements.wizardName ? elements.wizardName.value.trim() : '';
        if (customName) {
            wizardData.name = customName;
        }

        // Update summary
        if (elements.wizardSummaryName) {
            elements.wizardSummaryName.textContent = wizardData.name;
        }
        if (elements.wizardSummaryTracks) {
            elements.wizardSummaryTracks.textContent = wizardData.tracks;
        }
        if (elements.wizardSummarySize) {
            const estSize = wizardData.tracks * 8; // ~8MB per track
            elements.wizardSummarySize.textContent = `~${estSize} MB`;
        }

        wizardStep = 3;
        updateWizardStep();

    } else if (wizardStep === 3) {
        // Create playlist and optionally start sync
        elements.wizardNextBtn.disabled = true;
        elements.wizardNextBtn.textContent = 'Adding...';

        try {
            // Create the playlist
            const response = await fetch('/api/playlists', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: wizardData.name,
                    spotify_url: wizardData.url,
                    color: wizardData.color
                })
            });

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.error || 'Failed to create playlist');
            }

            const data = await response.json();

            closeWizard();

            // Reload playlists and select the new one
            await loadPlaylists();

            if (data.id) {
                await selectPlaylist(data.id);
            }

            // Start sync if checkbox is checked
            const downloadNow = elements.wizardDownloadNow ? elements.wizardDownloadNow.checked : false;
            if (downloadNow && wizardData.playlistInfo) {
                currentPlaylist = wizardData.playlistInfo;
                syncPreview = wizardData.playlistInfo.preview;
                displayPlaylist(wizardData.playlistInfo);

                // Start sync if there are new tracks
                if (syncPreview && syncPreview.new && syncPreview.new.length > 0) {
                    startSync();
                }
            }

            announceToScreenReader(`Playlist "${wizardData.name}" added successfully`);

        } catch (error) {
            await showModal('error', 'Create Failed', error.message);
        } finally {
            elements.wizardNextBtn.disabled = false;
            elements.wizardNextBtn.textContent = 'Add Playlist';
        }
    }
}

// ==================== SYNC CONFIRM MODAL ====================

function setupSyncConfirmModal() {
    if (!elements.syncConfirmOverlay) return;

    // Cancel button
    if (elements.syncConfirmCancel) {
        elements.syncConfirmCancel.addEventListener('click', closeSyncConfirmModal);
    }

    // Start button
    if (elements.syncConfirmStart) {
        elements.syncConfirmStart.addEventListener('click', confirmAndStartSync);
    }

    // Close on overlay click
    elements.syncConfirmOverlay.addEventListener('click', (e) => {
        if (e.target === elements.syncConfirmOverlay) {
            closeSyncConfirmModal();
        }
    });

    // Update summary when mode changes
    elements.syncModeRadios.forEach(radio => {
        radio.addEventListener('change', updateSyncSummary);
    });
}

function showSyncConfirmModal() {
    if (!syncPreview) {
        showModal('warning', 'No Playlist Loaded', 'Please load a playlist first');
        return;
    }

    const newCount = syncPreview.new ? syncPreview.new.length : 0;
    const removedCount = syncPreview.removed ? syncPreview.removed.length : 0;

    // If nothing to do, show message
    if (newCount === 0 && removedCount === 0) {
        showModal('success', 'Already Synced', 'Your playlist is already up to date!');
        return;
    }

    // If only new tracks and no removed, skip modal and start sync directly
    if (newCount > 0 && removedCount === 0) {
        startSync();
        return;
    }

    // Update counts in modal
    if (elements.syncNewCount) elements.syncNewCount.textContent = newCount;
    if (elements.syncNewCount2) elements.syncNewCount2.textContent = newCount;
    if (elements.syncRemovedCount) elements.syncRemovedCount.textContent = removedCount;
    if (elements.syncSummaryNew) elements.syncSummaryNew.textContent = newCount;
    if (elements.syncSummaryRemoved) elements.syncSummaryRemoved.textContent = removedCount;

    // Estimate download size (~8MB per track)
    const estSize = newCount * 8;
    if (elements.syncSummaryDownloadSize) {
        elements.syncSummaryDownloadSize.textContent = `~${estSize} MB`;
    }

    // Reset to append mode
    const appendRadio = document.querySelector('input[name="sync-mode"][value="append"]');
    if (appendRadio) appendRadio.checked = true;

    // Show/hide removed row based on mode
    updateSyncSummary();

    // Show modal
    if (elements.syncConfirmOverlay) {
        elements.syncConfirmOverlay.classList.remove('hidden');
    }
}

function closeSyncConfirmModal() {
    if (elements.syncConfirmOverlay) {
        elements.syncConfirmOverlay.classList.add('hidden');
    }
}

function updateSyncSummary() {
    const selectedMode = document.querySelector('input[name="sync-mode"]:checked');
    const isFullSync = selectedMode && selectedMode.value === 'sync';

    // Show/hide removed row
    if (elements.syncSummaryRemovedRow) {
        elements.syncSummaryRemovedRow.style.display = isFullSync ? 'flex' : 'none';
    }

    // Update toggle state to match selection
    if (elements.deleteRemovedToggle) {
        elements.deleteRemovedToggle.checked = isFullSync;
    }
}

function confirmAndStartSync() {
    const selectedMode = document.querySelector('input[name="sync-mode"]:checked');
    const deleteRemoved = selectedMode && selectedMode.value === 'sync';

    // Update the toggle to match selection
    if (elements.deleteRemovedToggle) {
        elements.deleteRemovedToggle.checked = deleteRemoved;
    }

    closeSyncConfirmModal();
    startSync();
}

// ==================== DEVICE COPY WIZARD ====================

let deviceWizardStep = 1;
let deviceWizardData = {
    destination: '',
    scanResult: null,
    copyMode: 'add'
};
let deviceCopyPollInterval = null;

// Device wizard elements
const deviceElements = {
    overlay: document.getElementById('device-wizard-overlay'),
    closeBtn: document.getElementById('device-wizard-close-btn'),
    backBtn: document.getElementById('device-wizard-back-btn'),
    nextBtn: document.getElementById('device-wizard-next-btn'),
    nextText: document.getElementById('device-wizard-next-text'),
    steps: document.querySelectorAll('#device-wizard-overlay .wizard-step'),
    contents: [
        document.getElementById('device-wizard-step-1'),
        document.getElementById('device-wizard-step-2'),
        document.getElementById('device-wizard-step-3')
    ],
    drivesList: document.getElementById('device-drives-list'),
    folderPath: document.getElementById('device-folder-path'),
    folderList: document.getElementById('device-folder-list'),
    browseUpBtn: document.getElementById('device-browse-up-btn'),
    scanLoading: document.getElementById('device-scan-loading'),
    scanResult: document.getElementById('device-scan-result'),
    destinationPath: document.getElementById('device-destination-path'),
    matchedCount: document.getElementById('device-matched-count'),
    missingCount: document.getElementById('device-missing-count'),
    extraCount: document.getElementById('device-extra-count'),
    spaceNeeded: document.getElementById('device-space-needed'),
    freeSpace: document.getElementById('device-free-space'),
    spaceWarning: document.getElementById('device-space-warning'),
    progressCircle: document.getElementById('device-progress-circle'),
    copyPercent: document.getElementById('device-copy-percent'),
    copyTrack: document.getElementById('device-copy-track'),
    copyCurrent: document.getElementById('device-copy-current'),
    copyTotal: document.getElementById('device-copy-total'),
    copySize: document.getElementById('device-copy-size'),
    copyComplete: document.getElementById('device-copy-complete'),
    copySummary: document.getElementById('device-copy-summary')
};

function initDeviceWizard() {
    // Copy to Device button
    const copyBtn = document.getElementById('copy-to-device-btn');
    if (copyBtn) {
        copyBtn.addEventListener('click', openDeviceWizard);
    }

    // Close button
    if (deviceElements.closeBtn) {
        deviceElements.closeBtn.addEventListener('click', closeDeviceWizard);
    }

    // Back button
    if (deviceElements.backBtn) {
        deviceElements.backBtn.addEventListener('click', deviceWizardBack);
    }

    // Next button
    if (deviceElements.nextBtn) {
        deviceElements.nextBtn.addEventListener('click', deviceWizardNext);
    }

    // Folder path input - on Enter, browse to that path
    if (deviceElements.folderPath) {
        deviceElements.folderPath.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                const path = deviceElements.folderPath.value.trim();
                if (path) {
                    deviceWizardData.destination = path;
                    await browseFolder(path);
                }
            }
        });
    }

    // Browse up button
    if (deviceElements.browseUpBtn) {
        deviceElements.browseUpBtn.addEventListener('click', async () => {
            const currentPath = deviceElements.folderPath.value.trim();
            if (currentPath) {
                // Go up one directory
                const parentPath = currentPath.replace(/[\/\\][^\/\\]+$/, '') || '/';
                await browseFolder(parentPath);
            }
        });
    }

    // Copy mode radio buttons
    document.querySelectorAll('input[name="device-copy-mode"]').forEach(radio => {
        radio.addEventListener('change', () => {
            deviceWizardData.copyMode = radio.value;
        });
    });

    // ESC to close
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && deviceElements.overlay && !deviceElements.overlay.classList.contains('hidden')) {
            closeDeviceWizard();
        }
    });
}

async function openDeviceWizard() {
    if (!currentPlaylistId) {
        await showModal('warning', 'No Playlist', 'Please select a playlist first');
        return;
    }

    // Reset wizard state
    deviceWizardStep = 1;
    deviceWizardData = {
        destination: '',
        scanResult: null,
        copyMode: 'add'
    };

    // Reset UI
    if (deviceElements.folderPath) deviceElements.folderPath.value = '';
    document.querySelectorAll('input[name="device-copy-mode"]').forEach(radio => {
        radio.checked = radio.value === 'add';
    });

    // Show wizard
    if (deviceElements.overlay) {
        deviceElements.overlay.classList.remove('hidden');
    }

    // Load drives
    await loadDeviceDrives();

    updateDeviceWizardStep();
}

function closeDeviceWizard() {
    if (deviceElements.overlay) {
        deviceElements.overlay.classList.add('hidden');
    }
    if (deviceCopyPollInterval) {
        clearInterval(deviceCopyPollInterval);
        deviceCopyPollInterval = null;
    }
}

function updateDeviceWizardStep() {
    // Update step indicators
    deviceElements.steps.forEach((step, index) => {
        const stepNum = index + 1;
        step.classList.remove('active', 'completed');
        if (stepNum === deviceWizardStep) {
            step.classList.add('active');
        } else if (stepNum < deviceWizardStep) {
            step.classList.add('completed');
        }
    });

    // Show/hide content
    deviceElements.contents.forEach((content, index) => {
        if (content) {
            content.classList.toggle('hidden', index + 1 !== deviceWizardStep);
        }
    });

    // Update buttons
    if (deviceElements.backBtn) {
        deviceElements.backBtn.classList.toggle('hidden', deviceWizardStep === 1 || deviceWizardStep === 3);
    }
    if (deviceElements.nextText) {
        if (deviceWizardStep === 1) {
            deviceElements.nextText.textContent = 'Continue';
        } else if (deviceWizardStep === 2) {
            deviceElements.nextText.textContent = 'Start Copy';
        } else {
            deviceElements.nextText.textContent = 'Done';
        }
    }
}

function deviceWizardBack() {
    if (deviceWizardStep > 1) {
        deviceWizardStep--;
        updateDeviceWizardStep();
    }
}

async function deviceWizardNext() {
    if (deviceWizardStep === 1) {
        // Validate destination
        const destination = deviceElements.folderPath ? deviceElements.folderPath.value.trim() : '';
        if (!destination) {
            await showModal('warning', 'No Destination', 'Please select a destination folder');
            return;
        }

        deviceWizardData.destination = destination;

        // Move to step 2 and scan
        deviceWizardStep = 2;
        updateDeviceWizardStep();
        await scanDestination();

    } else if (deviceWizardStep === 2) {
        // Start copy
        deviceWizardStep = 3;
        updateDeviceWizardStep();
        await startDeviceCopy();

    } else {
        // Done - close wizard
        closeDeviceWizard();
    }
}

async function loadDeviceDrives() {
    if (!deviceElements.drivesList) return;

    deviceElements.drivesList.innerHTML = `
        <div class="device-loading">
            <div class="spinner"></div>
            <span>Scanning for drives...</span>
        </div>
    `;

    try {
        const response = await fetch('/api/devices');
        const data = await response.json();

        if (data.drives && data.drives.length > 0) {
            deviceElements.drivesList.innerHTML = data.drives.map(drive => {
                const isSwim = (drive.volume_label || '').toUpperCase().startsWith('SWIM');
                const swimClass = isSwim ? ' swim-device' : '';
                // Select icon based on drive type
                let icon;
                if (isSwim) {
                    icon = '<path d="M22 12c-2.5 0-4.5 2.5-7 2.5S9.5 12 7 12s-5 2.5-5 2.5"/><path d="M22 17c-2.5 0-4.5-2.5-7-2.5S9.5 17 7 17s-5-2.5-5-2.5"/><circle cx="12" cy="7" r="3"/>';
                } else if (drive.is_removable) {
                    icon = '<rect x="4" y="4" width="16" height="16" rx="2"/><line x1="4" y1="9" x2="20" y2="9"/>';
                } else {
                    icon = '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/>';
                }
                return `
                    <button class="device-drive-item${swimClass}" data-path="${escapeHtml(drive.path)}">
                        <div class="device-drive-icon">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                ${icon}
                            </svg>
                        </div>
                        <div class="device-drive-info">
                            <span class="device-drive-name">${escapeHtml(drive.name)}</span>
                            <span class="device-drive-space">${drive.free_gb} GB free</span>
                        </div>
                    </button>
                `;
            }).join('');

            // Add click handlers
            deviceElements.drivesList.querySelectorAll('.device-drive-item').forEach(item => {
                item.addEventListener('click', async () => {
                    // Remove selected from all
                    deviceElements.drivesList.querySelectorAll('.device-drive-item').forEach(i =>
                        i.classList.remove('selected'));
                    item.classList.add('selected');

                    const path = item.dataset.path;
                    if (deviceElements.folderPath) {
                        deviceElements.folderPath.value = path;
                    }
                    deviceWizardData.destination = path;
                    await browseFolder(path);
                });
            });

            // If last used path exists, pre-fill it
            if (data.last_used) {
                if (deviceElements.folderPath) {
                    deviceElements.folderPath.value = data.last_used;
                }
                deviceWizardData.destination = data.last_used;
                await browseFolder(data.last_used);
            }
        } else {
            deviceElements.drivesList.innerHTML = `
                <div class="device-no-drives">
                    <p>No removable drives found</p>
                    <p class="device-hint">Enter a path manually below</p>
                </div>
            `;
        }
    } catch (error) {
        deviceElements.drivesList.innerHTML = `
            <div class="device-error">
                <p>Failed to scan drives</p>
            </div>
        `;
    }
}

async function browseFolder(path) {
    if (!deviceElements.folderList) return;

    deviceElements.folderList.innerHTML = `
        <div class="device-loading">
            <div class="spinner"></div>
            <span>Loading...</span>
        </div>
    `;

    try {
        const response = await fetch('/api/devices/browse', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
        });

        const data = await response.json();

        if (!response.ok) {
            deviceElements.folderList.innerHTML = `<div class="device-error">${escapeHtml(data.error || 'Failed to browse')}</div>`;
            return;
        }

        if (deviceElements.folderPath) {
            deviceElements.folderPath.value = data.path;
        }
        deviceWizardData.destination = data.path;

        if (data.folders && data.folders.length > 0) {
            deviceElements.folderList.innerHTML = data.folders.map(folder => `
                <button class="device-folder-item" data-path="${escapeHtml(folder.path)}">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                        <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
                    </svg>
                    <span>${escapeHtml(folder.name)}</span>
                </button>
            `).join('');

            deviceElements.folderList.querySelectorAll('.device-folder-item').forEach(item => {
                item.addEventListener('click', async () => {
                    await browseFolder(item.dataset.path);
                });
            });
        } else {
            deviceElements.folderList.innerHTML = `
                <div class="device-empty-folder">
                    <p>No subfolders (this folder will be used)</p>
                </div>
            `;
        }
    } catch (error) {
        deviceElements.folderList.innerHTML = `<div class="device-error">Error browsing folder</div>`;
    }
}

async function scanDestination() {
    if (deviceElements.scanLoading) deviceElements.scanLoading.classList.remove('hidden');
    if (deviceElements.scanResult) deviceElements.scanResult.classList.add('hidden');

    try {
        const response = await fetch('/api/devices/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: deviceWizardData.destination })
        });

        const data = await response.json();

        if (!response.ok) {
            await showModal('error', 'Scan Failed', data.error || 'Failed to scan destination');
            deviceWizardStep = 1;
            updateDeviceWizardStep();
            return;
        }

        deviceWizardData.scanResult = data;

        // Update UI
        if (deviceElements.destinationPath) deviceElements.destinationPath.textContent = data.path;
        if (deviceElements.matchedCount) deviceElements.matchedCount.textContent = data.matched_count;
        if (deviceElements.missingCount) deviceElements.missingCount.textContent = data.missing_count;
        if (deviceElements.extraCount) deviceElements.extraCount.textContent = data.extra_count;
        if (deviceElements.spaceNeeded) deviceElements.spaceNeeded.textContent = `${data.missing_size_mb} MB`;
        if (deviceElements.freeSpace) deviceElements.freeSpace.textContent = `${data.free_gb} GB`;

        // Show/hide space warning
        if (deviceElements.spaceWarning) {
            deviceElements.spaceWarning.classList.toggle('hidden', data.has_space);
        }

    } catch (error) {
        await showModal('error', 'Scan Failed', error.message);
        deviceWizardStep = 1;
        updateDeviceWizardStep();
    } finally {
        if (deviceElements.scanLoading) deviceElements.scanLoading.classList.add('hidden');
        if (deviceElements.scanResult) deviceElements.scanResult.classList.remove('hidden');
    }
}

async function startDeviceCopy() {
    // Hide complete, show progress
    if (deviceElements.copyComplete) deviceElements.copyComplete.classList.add('hidden');

    // Reset progress
    updateDeviceCopyProgress(0, 0, 0, 'Preparing...');

    try {
        const response = await fetch('/api/devices/copy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                destination: deviceWizardData.destination,
                mode: deviceWizardData.copyMode
            })
        });

        const data = await response.json();

        if (!response.ok) {
            await showModal('error', 'Copy Failed', data.error || 'Failed to start copy');
            deviceWizardStep = 2;
            updateDeviceWizardStep();
            return;
        }

        // Start polling for progress
        deviceCopyPollInterval = setInterval(pollDeviceCopyStatus, 500);

    } catch (error) {
        await showModal('error', 'Copy Failed', error.message);
        deviceWizardStep = 2;
        updateDeviceWizardStep();
    }
}

async function pollDeviceCopyStatus() {
    try {
        const response = await fetch('/api/devices/copy/status');
        const data = await response.json();

        const percent = data.total > 0 ? Math.round((data.current / data.total) * 100) : 0;
        const sizeMB = Math.round(data.bytes_copied / (1024 * 1024));

        updateDeviceCopyProgress(percent, data.current, data.total, data.current_track, sizeMB);

        if (!data.is_copying) {
            clearInterval(deviceCopyPollInterval);
            deviceCopyPollInterval = null;

            if (data.status === 'completed') {
                showDeviceCopyComplete(data.copied_count, data.deleted_count);
            } else if (data.status === 'error') {
                await showModal('error', 'Copy Failed', data.error || 'An error occurred');
            }
        }
    } catch (error) {
        console.error('Failed to poll copy status:', error);
    }
}

function updateDeviceCopyProgress(percent, current, total, trackName, sizeMB = 0) {
    if (deviceElements.copyPercent) deviceElements.copyPercent.textContent = `${percent}%`;
    if (deviceElements.copyCurrent) deviceElements.copyCurrent.textContent = current;
    if (deviceElements.copyTotal) deviceElements.copyTotal.textContent = total;
    if (deviceElements.copyTrack) deviceElements.copyTrack.textContent = trackName || 'Preparing...';
    if (deviceElements.copySize) deviceElements.copySize.textContent = `${sizeMB} MB copied`;

    // Update progress ring
    if (deviceElements.progressCircle) {
        const circumference = 2 * Math.PI * 45;
        const offset = circumference - (percent / 100) * circumference;
        deviceElements.progressCircle.style.strokeDasharray = circumference;
        deviceElements.progressCircle.style.strokeDashoffset = offset;
    }
}

function showDeviceCopyComplete(copiedCount, deletedCount) {
    if (deviceElements.copyComplete) {
        deviceElements.copyComplete.classList.remove('hidden');
    }

    let summary = `${copiedCount} tracks copied`;
    if (deletedCount > 0) {
        summary += `, ${deletedCount} removed`;
    }
    if (deviceElements.copySummary) {
        deviceElements.copySummary.textContent = summary;
    }

    // Update button text
    if (deviceElements.nextText) {
        deviceElements.nextText.textContent = 'Done';
    }
}

// Initialize device wizard on page load
document.addEventListener('DOMContentLoaded', initDeviceWizard);
