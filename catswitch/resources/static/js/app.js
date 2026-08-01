const DEFAULT_DETECTED_LOCAL_LIST_NAME = 'Detected Games List';

/** Render a Heroicon from /static/img via CSS mask (supports currentColor). */
function icon(name, sizeClass = 'icon-md') {
    return `<span class="icon icon-${name} ${sizeClass}" aria-hidden="true"></span>`;
}

// App state globals
const appState = {
    isTitleEditing: false,
    categoryLocked: false,
    titleLocked: false,
    currentCategory: null,
    fullCategoryName: null, // Store the full untruncated category name
    currentTitle: '',
    titleTemplate: '',
    streamInfo: null,
    auth: null,
    sessionBooted: false,
    activeTab: 'home',  // Default tab is home
    activeSubtab: 'apps',  // Default subtab is apps
    excludedApps: {
        lists: [],
        selectedList: null
    },
    apps: {
        lists: [],
        selectedList: null,
        canSaveDetectedGames: true,
        editingUrlList: null
    },
    detectedApps: {
        apps: [],
        selectedApp: null,
        writableLists: [],
        lists: []
    },
    detectionSettings: {
        default_category: 'Just Chatting',
        switch_delay_seconds: 0,
        auto_lock_category_on_manual_update: true,
        auto_lock_title_on_manual_update: true,
        use_discord_detectable: true,
    },
    theme: 'Default.css',
};

// Store EventSource for game detection
let eventSource = null;

// DOM Elements
const elements = {
    minimizeBtn: document.getElementById('minimize-button'),
    closeBtn: document.getElementById('close-button'),
    channelName: document.getElementById('channel-name'),
    categoryLabel: document.getElementById('current-category'),
    categoryInput: document.getElementById('category-search'),
    categorySearch: document.getElementById('category-search'),
    categoryContainer: document.querySelector('.category-display'),
    categorySearchResults: document.getElementById('category-search-results'),
    titleLabel: document.getElementById('stream-title'),
    titleInput: document.getElementById('title-input'),
    titleContainer: document.querySelector('.title-display'),
    categoryLock: document.getElementById('category-lock'),
    titleLock: document.getElementById('title-lock'),
    categoryEditContainer: document.querySelector('.category-edit'),
    titleEditContainer: document.querySelector('.title-edit'),
    categoryImage: document.getElementById('category-image'),
    titleBar: document.querySelector('.title-bar'),
    
    // Games & Apps tab elements
    subtabButtons: document.querySelectorAll('.subtab-button'),
    excludedAppsList: document.getElementById('excluded-apps-list'),
    addListBtn: document.getElementById('add-list-btn'),
    editBtn: document.getElementById('edit-btn'),
    removeBtn: document.getElementById('remove-btn'),
    reloadBtn: document.getElementById('excluded-reload-btn'),
    openExcludedFileBtn: document.getElementById('open-excluded-file-btn'),
    
    // Detected Apps tab elements
    detectedAppsList: document.getElementById('detected-apps-list'),
    
    // Modal elements
    modalOverlay: document.getElementById('modal-overlay'),
    modalTitle: document.getElementById('modal-title'),
    modalContent: document.getElementById('modal-content'),
    modalClose: document.getElementById('modal-close'),
    modalCancel: document.getElementById('modal-cancel'),
    modalConfirm: document.getElementById('modal-confirm'),
    
    // New modals
    addListModal: document.getElementById('addListModal'),
    createNewListModal: document.getElementById('createNewListModal'),
    addLocalListModal: document.getElementById('addLocalListModal'),
    addFromUrlModal: document.getElementById('addFromUrlModal'),
    
    // New modal elements
    newListName: document.getElementById('newListName'),
    createNewListBtn: document.getElementById('createNewListBtn'),
    localListPath: document.getElementById('localListPath'),
    addLocalListShowFolderBtn: document.getElementById('addLocalListShowFolderBtn'),
    addLocalListOkBtn: document.getElementById('addLocalListOkBtn'),
    listUrl: document.getElementById('listUrl'),
    listName: document.getElementById('listName'),
    addFromUrlBtn: document.getElementById('addFromUrlBtn'),
    
    // Option elements
    createNewListOption: document.getElementById('createNewListOption'),
    addLocalListOption: document.getElementById('addLocalListOption'),
    addFromUrlOption: document.getElementById('addFromUrlOption'),
    
    // New for excluded apps
    createNewOption: document.getElementById('createNewOption'),
    addLocalOption: document.getElementById('addLocalOption'),
    reloadExcludedAppsBtn: document.getElementById('excluded-reload-btn'),
    cancelNewListBtn: document.getElementById('cancelNewListBtn'),
    cancelUrlBtn: document.getElementById('cancelUrlBtn'),
    addUrlBtn: document.getElementById('addUrlBtn'),

    // Settings tab
    settingsDefaultCategory: document.getElementById('settings-default-category'),
    settingsDefaultCategoryResults: document.getElementById('settings-default-category-results'),
    settingsSwitchDelay: document.getElementById('settings-switch-delay'),
    settingsAutoLockCategory: document.getElementById('settings-auto-lock-category'),
    settingsAutoLockTitle: document.getElementById('settings-auto-lock-title'),
    settingsUseDiscordDetectable: document.getElementById('settings-use-discord-detectable'),
    settingsMinimizeToTray: document.getElementById('settings-minimize-to-tray'),
    settingsAutostartWindows: document.getElementById('settings-autostart-windows'),
    settingsTheme: document.getElementById('settings-theme'),
    settingsOpenThemesFolderBtn: document.getElementById('settings-open-themes-folder'),
};

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', async function() {
    if (await handleExternalOAuthCallback()) {
        hideAppLoading();
        return;
    }

    document.body.classList.add('app-loading-locked');
    appLoadingDepth = 1;

    try {
        await ensureInternetAtStartup();

        await loadHomeViewPreference();

        setupWindowControls();
        setupWindowDragging();
        setupTabSwitching();
        setupSubtabSwitching();
        setupExcludedApps();
        setupApps();
        setupEventListeners();
        setupRemoveAppModal();
        setupExcludeAppModal();
        setupAccountAuth();
        setupHomeQuickActions();
        setupDetectedAppsBackToTop();
        setupHelpIconTooltips();
        setupTitlePresets();
        setupInfoConsole();
        setupDetectionSettings();
        setupUpdates();
        loadDetectionSettings();
        loadWindowSettings();
        loadAndApplyTheme();

        try {
            await handleOAuthRedirectFromUrl();
        } catch (error) {
            console.error('OAuth redirect handling failed:', error);
            showToast(error.message || 'Login failed');
        }

        await initializeApp();
        await ensureHomeViewWindowSize(homeViewState.width, homeViewState.height);
    } finally {
        hideAppLoading();
    }
});

// F12 key handler for debug console
document.addEventListener('keydown', function(event) {
    if (event.key === 'F12') {
        event.preventDefault();
        toggleDebugConsole();
    }
});

// Toggle debug console visibility
function toggleDebugConsole() {
    try {
        
        // Request the backend to restart with debug enabled
        if (typeof pywebview !== 'undefined' && pywebview.api && pywebview.api.js_toggle_debug) {
            pywebview.api.js_toggle_debug();
        }
    } catch (error) {
    }
}

// Setup window controls
function setupWindowControls() {
    
    if (elements.minimizeBtn) {
        elements.minimizeBtn.addEventListener('click', function() {
            minimizeWindow();
        });
    }
    
    if (elements.closeBtn) {
        elements.closeBtn.addEventListener('click', function() {
            closeWindow();
        });
    }
}

// Minimize the window
function minimizeWindow() {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.js_minimize_window === 'function') {
        window.pywebview.api.js_minimize_window().catch(err => {
            showToast(`Error minimizing window: ${err.message}`);
            console.error('Error minimizing window:', err);
        });
    } else {
        // Fallback to API
        fetch('/api/window-control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'minimize' })
        }).catch(err => {
            showToast(`Error minimizing window: ${err.message}`);
            console.error('Error minimizing window:', err);
        });
    }
}

// Close the window
function closeWindow() {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.js_close_window === 'function') {
        window.pywebview.api.js_close_window().catch(err => {
            showToast(`Error closing window: ${err.message}`);
            console.error('Error closing window:', err);
        });
    } else {
        // Fallback to API
        fetch('/api/window-control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'close' })
        }).catch(err => {
            showToast(`Error closing window: ${err.message}`);
            console.error('Error closing window:', err);
        });
    }
}

// API Functions
async function fetchData(endpoint, options = {}) {
    try {
        const response = await fetch(`/api/${endpoint}`, options);
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        const responseData = await response.json();
        return responseData;
    } catch (error) {
        console.error('API Error:', error);
        return { success: false, error: error.message };
    }
}

async function getStreamInfo() {
    return await fetchData('stream-info');
}

// Add a variable to track the current suggestions
let currentSuggestions = [];

// Update the searchCategories function to store the suggestions
function searchCategories(query) {
    
    fetch(`/api/categories?query=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(data => {
            // Store the suggestions globally
            currentSuggestions = data || [];
            renderCategoryResults(data);
        })
        .catch(error => {
        });
}

async function updateCategory(categoryName) {
    // Check if an update was recently performed (within last 2 seconds)
    const now = Date.now();
    if (window._lastCategoryUpdateCompleteTime && (now - window._lastCategoryUpdateCompleteTime < 2000)) {
        console.log('Ignoring rapid category update request');
        showToast('Please wait before updating again');
        return;
    }
    
    // Set a flag to avoid duplicate UI updates
    const updateTimestamp = Date.now();
    window._lastCategoryUpdateTimestamp = updateTimestamp;
    
    fetch('/api/update-category', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            category_name: categoryName
        })
    })
    .then(response => response.json())
    .then(data => {
        // Log the complete response for debugging
        console.log('Category update response:', data);
        
        // Skip if a newer update has been initiated
        if (window._lastCategoryUpdateTimestamp !== updateTimestamp) {
            console.log('Skipping obsolete update response');
            return;
        }
        
        // Record the time when update completed
        window._lastCategoryUpdateCompleteTime = Date.now();
        
        // Check response status
        if (data.status === 'success') {
            console.log('Category updated successfully');
            
            // If response includes box art, update the UI
            if (data.box_art_url) {
                // Get and store the full category name from the response
                const fullCategoryName = data.full_category_name || categoryName;
                
                // Store full name in app state
                if (window.appState) {
                    window.appState.fullCategoryName = fullCategoryName;
                }
                
                // Update all UI elements with the full category name
                gameDetected(fullCategoryName, data.box_art_url, true);
            }
            
            // Auto-lock the category when manually set (if enabled in settings)
            if (data.lock_applied) {
                appState.categoryLocked = true;
                updateCategoryLockDisplay(true);
                showToast('Manual category set - Automatic updates have been locked');
            } else if (
                !appState.categoryLocked
                && appState.detectionSettings.auto_lock_category_on_manual_update
            ) {
                toggleCategoryLock();
                showToast('Manual category set - Automatic updates have been locked');
            }
        } 
        // Do not show any error for "success" status even without box art
        else if (data.error) {
            console.error('Error updating category:', data.error);
            showToast('Failed to update category');
        }
    })
    .catch(error => {
        console.error('Error updating category:', error);
        showToast('Failed to update category');
        window._lastCategoryUpdateCompleteTime = Date.now(); // Mark as complete even on error
    });
}

async function updateTitle(title) {
    return await fetchData('update-title', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ title })
    });
}

async function setAlwaysOnTop(enabled) {
    
    // Check what APIs are available
    if (window.pywebview) {
        if (window.pywebview.api) {
        }
    }
    
    // Try to use pywebview API if available
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.js_set_always_on_top === 'function') {
        try {
            const result = await window.pywebview.api.js_set_always_on_top(enabled);
            
            if (result) {
                homeViewState.alwaysOnTop = enabled;
                updateAlwaysOnTopButton();
                return true;
            } else {
            }
        } catch (e) {
            console.error('Failed to use pywebview API:', e);
            showToast(`Error setting always on top: ${e.message}`);
        }
    } else {
    }
    
    // Fall back to server API if pywebview is not available or failed
    try {
        const result = await fetchData('always-on-top', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ enabled })
        });
        
        
        // Only show toast on error
        if (!result || !result.success) {
            showToast('Failed to set always on top');
            return false;
        }
        
        homeViewState.alwaysOnTop = enabled;
        updateAlwaysOnTopButton();
        return true;
    } catch (e) {
        console.error('Failed to use server API:', e);
        showToast(`Error setting always on top: ${e.message}`);
        return false;
    }
}

// UI Functions
async function initializeApp() {

    if (window.current_twitch_category === undefined) {
        window.current_twitch_category = '';
    }

    const authStatus = await fetchAuthStatus();
    appState.auth = authStatus;

    if (!authStatus.authenticated) {
        showWelcomeScreen();
        return;
    }

    hideWelcomeScreen();
    await bootAuthenticatedSession();
}

async function bootAuthenticatedSession() {
    if (appState.sessionBooted) {
        return;
    }
    appState.sessionBooted = true;

    try {
        const streamInfo = await getStreamInfo();
        if (streamInfo && streamInfo.broadcaster_name) {
            updateUIWithStreamInfo(streamInfo);
            window.current_twitch_category = streamInfo.game_name;
            console.log('Initial window.current_twitch_category:', window.current_twitch_category);
        }
    } catch (error) {
        if (error.message !== 'Not authenticated') {
            showToast('Failed to get stream info');
        }
    }

    startGameDetection();

    try {
        let isAlwaysOnTop = false;

        if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.js_is_always_on_top === 'function') {
            try {
                isAlwaysOnTop = await window.pywebview.api.js_is_always_on_top();
            } catch (e) {
            }
        }

        homeViewState.alwaysOnTop = isAlwaysOnTop;
        updateAlwaysOnTopButton();
    } catch (error) {
    }
}

async function fetchAuthStatus() {
    const response = await fetch('/api/auth/status');
    if (!response.ok) {
        throw new Error('Failed to fetch auth status');
    }
    return response.json();
}

async function completeOAuthLogin(token) {
    const response = await fetch('/api/auth/complete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token })
    });
    const data = await response.json();
    if (!response.ok || !data.success) {
        throw new Error(data.error || 'Failed to complete login');
    }
    return data;
}

function setOAuthCallbackState(state, title, message) {
    const icon = document.getElementById('oauth-callback-icon');
    const titleEl = document.getElementById('oauth-callback-title');
    const messageEl = document.getElementById('oauth-callback-message');

    if (icon) {
        icon.dataset.state = state;
    }
    if (titleEl && title) {
        titleEl.textContent = title;
    }
    if (messageEl && message) {
        messageEl.textContent = message;
    }
}

async function finishOAuthLogin(authData) {
    appState.auth = authData || await fetchAuthStatus();
    hideWelcomeScreen();
    appState.sessionBooted = false;
    await bootAuthenticatedSession();

    if (appState.auth.accounts) {
        renderAccountList(appState.auth.accounts, appState.auth.active_login);
    }

    const displayName = appState.auth.user?.display_name || appState.auth.active_login;
    if (displayName) {
        showToast(`Signed in as ${displayName}`);
    }
}

function isOAuthCallbackUrl() {
    const hash = window.location.hash.substring(1);
    if (hash) {
        const params = new URLSearchParams(hash);
        if (params.get('access_token') || params.get('error')) {
            return true;
        }
    }
    const query = new URLSearchParams(window.location.search);
    return Boolean(query.get('access_token') || query.get('error'));
}

function isExternalBrowser() {
    return !(window.pywebview && window.pywebview.api);
}

function parseOAuthFromUrl() {
    let token = null;
    let errorMessage = null;

    const hash = window.location.hash.substring(1);
    if (hash) {
        const params = new URLSearchParams(hash);
        token = params.get('access_token');
        errorMessage = params.get('error_description') || params.get('error');
    }

    if (!token) {
        const params = new URLSearchParams(window.location.search);
        token = params.get('access_token');
        if (!errorMessage) {
            errorMessage = params.get('error_description') || params.get('error');
        }
    }

    return { token, errorMessage };
}

async function requestAppFocus() {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.js_focus_window === 'function') {
        try {
            await window.pywebview.api.js_focus_window();
            return;
        } catch (error) {
        }
    }

    try {
        await fetch('/api/window-control', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'focus' })
        });
    } catch (error) {
    }
}

async function handleExternalOAuthCallback() {
    if (!isOAuthCallbackUrl() || !isExternalBrowser()) {
        return false;
    }

    document.body.classList.add('oauth-callback-page');
    const screen = document.getElementById('oauth-callback-screen');
    if (screen) {
        screen.classList.remove('hidden');
    }
    setOAuthCallbackState('loading', 'Signing you in…', 'Returning to CatSwitch…');

    const { token, errorMessage } = parseOAuthFromUrl();
    window.history.replaceState(null, '', window.location.pathname);

    if (errorMessage) {
        setOAuthCallbackState('error', 'Login failed', errorMessage);
        return true;
    }

    if (!token) {
        setOAuthCallbackState('error', 'Login failed', 'No access token found.');
        return true;
    }

    try {
        await completeOAuthLogin(token);
        await requestAppFocus();
        setOAuthCallbackState('success', 'Login successful', 'You can close this tab.');
        setTimeout(() => {
            window.close();
        }, 1200);
    } catch (error) {
        setOAuthCallbackState('error', 'Login failed', error.message || 'Something went wrong.');
    }

    return true;
}

function showWelcomeScreen() {
    document.body.classList.add('auth-required');
    const welcome = document.getElementById('welcome-screen');
    if (welcome) {
        welcome.classList.remove('hidden');
    }
    if (elements.channelName) {
        elements.channelName.textContent = 'Not signed in';
        elements.channelName.disabled = true;
    }
}

function hideWelcomeScreen() {
    document.body.classList.remove('auth-required');
    const welcome = document.getElementById('welcome-screen');
    if (welcome) {
        welcome.classList.add('hidden');
    }
    const status = document.getElementById('welcome-login-status');
    if (status) {
        status.classList.add('hidden');
        status.textContent = '';
    }
    if (elements.channelName) {
        elements.channelName.disabled = false;
    }
}

async function handleOAuthRedirectFromUrl() {
    if (!isOAuthCallbackUrl() || isExternalBrowser()) {
        return false;
    }

    const { token, errorMessage } = parseOAuthFromUrl();

    if (errorMessage) {
        window.history.replaceState(null, '', window.location.pathname);
        throw new Error(errorMessage);
    }

    if (!token) {
        return false;
    }

    window.history.replaceState(null, '', window.location.pathname);
    const data = await completeOAuthLogin(token);
    await finishOAuthLogin({
        authenticated: true,
        active_login: data.active_login,
        accounts: data.accounts,
        user: data.user
    });
    return true;
}

let authPollTimer = null;
let authPollBaseline = null;

function stopAuthPolling() {
    if (authPollTimer) {
        clearInterval(authPollTimer);
        authPollTimer = null;
    }
}

function authLoginCompleted(status) {
    if (!status.authenticated) {
        return false;
    }
    if (!authPollBaseline) {
        return true;
    }
    if (!authPollBaseline.wasAuthenticated) {
        return true;
    }
    if (status.active_login !== authPollBaseline.active_login) {
        return true;
    }
    const accounts = status.accounts || [];
    return accounts.some((account) => !authPollBaseline.accountLogins.has(account.login));
}

function startAuthPolling(onSuccess) {
    stopAuthPolling();
    let attempts = 0;
    authPollTimer = setInterval(async () => {
        attempts += 1;
        try {
            const status = await fetchAuthStatus();
            if (authLoginCompleted(status)) {
                stopAuthPolling();
                authPollBaseline = null;
                await requestAppFocus();
                if (typeof onSuccess === 'function') {
                    onSuccess(status);
                }
            } else if (attempts >= 120) {
                stopAuthPolling();
                authPollBaseline = null;
            }
        } catch (error) {
        }
    }, 1500);
}

async function beginTwitchLogin(statusElement, options = {}) {
    const loginButtons = [
        document.getElementById('welcome-login-btn'),
        document.getElementById('add-account-btn')
    ];

    loginButtons.forEach((btn) => {
        if (btn) btn.disabled = true;
    });

    let devicePollTimer = null;
    const stopDevicePoll = () => {
        if (devicePollTimer) {
            clearTimeout(devicePollTimer);
            devicePollTimer = null;
        }
    };

    const showStatus = (text) => {
        if (statusElement) {
            statusElement.classList.remove('hidden');
            statusElement.textContent = text;
        }
    };

    try {
        showStatus('Starting Twitch login…');
        const response = await fetch('/api/auth/device/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ open_browser: true })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to start Twitch login');
        }

        const userCode = data.user_code || '';
        showStatus(
            userCode
                ? `Confirm in your browser. Code: ${userCode}`
                : 'Confirm the login in your browser…'
        );

        const intervalMs = Math.max(3, Number(data.interval) || 5) * 1000;
        const deadline = Date.now() + (Number(data.expires_in) || 1800) * 1000;

        await new Promise((resolve, reject) => {
            const tick = async () => {
                if (Date.now() > deadline) {
                    reject(new Error('Login timed out — try again'));
                    return;
                }
                try {
                    const pollResponse = await fetch('/api/auth/device/poll', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: '{}'
                    });
                    const poll = await pollResponse.json();
                    const status = poll.status;

                    if (status === 'success') {
                        stopDevicePoll();
                        await requestAppFocus();
                        await finishOAuthLogin({
                            authenticated: true,
                            active_login: poll.active_login,
                            accounts: poll.accounts,
                            user: poll.user
                        });
                        if (statusElement) {
                            statusElement.classList.add('hidden');
                            statusElement.textContent = '';
                        }
                        resolve();
                        return;
                    }
                    if (status === 'denied') {
                        reject(new Error('Login was denied'));
                        return;
                    }
                    if (status === 'expired') {
                        reject(new Error('Login code expired — try again'));
                        return;
                    }
                    if (status === 'error') {
                        reject(new Error(poll.error || 'Login failed'));
                        return;
                    }

                    if (userCode) {
                        showStatus(`Confirm in your browser. Code: ${userCode}`);
                    }
                    const waitMs = (poll.retry_after ? Number(poll.retry_after) * 1000 : null)
                        || (status === 'slow_down' ? intervalMs + 5000 : intervalMs);
                    devicePollTimer = setTimeout(tick, waitMs);
                } catch (error) {
                    reject(error);
                }
            };
            devicePollTimer = setTimeout(tick, intervalMs);
        });
    } catch (error) {
        stopDevicePoll();
        try {
            await fetch('/api/auth/device/cancel', { method: 'POST' });
        } catch (_e) {
        }
        if (statusElement) {
            statusElement.textContent = error.message || 'Login failed';
        }
        showToast(error.message || 'Login failed');
    } finally {
        stopDevicePoll();
        loginButtons.forEach((btn) => {
            if (btn) btn.disabled = false;
        });
    }
}

// ============================================================================
// Home quick actions & compact view
// ============================================================================

const homeViewState = {
    compact: false,
    width: 550,
    height: 440,
    alwaysOnTop: false,
    accountModalRestoreCompact: false,
    editGameRestoreCompact: false,
};

async function resizeAppWindow(width, height) {
    if (window.pywebview && window.pywebview.api && typeof window.pywebview.api.js_resize_window === 'function') {
        try {
            return await window.pywebview.api.js_resize_window(width, height);
        } catch (error) {
        }
    }
    return false;
}

function updateHomeViewToggleButton() {
    const btn = document.getElementById('homeViewToggleBtn');
    if (!btn) return;

    const icon = btn.querySelector('.home-view-toggle-icon');
    if (homeViewState.compact) {
        btn.title = 'Full view';
        if (icon) {
            icon.classList.remove('icon-arrows-pointing-in');
            icon.classList.add('icon-arrows-pointing-out');
        }
    } else {
        btn.title = 'Compact view';
        if (icon) {
            icon.classList.remove('icon-arrows-pointing-out');
            icon.classList.add('icon-arrows-pointing-in');
        }
    }
}

function updateAlwaysOnTopButton() {
    const btn = document.getElementById('homeAlwaysOnTopBtn');
    if (!btn) return;
    btn.classList.toggle('active', homeViewState.alwaysOnTop);
    btn.title = homeViewState.alwaysOnTop ? 'Always on top (on)' : 'Always on top';
}

async function loadHomeViewPreference() {
    try {
        const response = await fetch('/api/home-view');
        const data = await response.json();
        homeViewState.compact = !!data.compact;
        homeViewState.width = data.width;
        homeViewState.height = data.height;
        document.body.classList.toggle('home-compact-view', homeViewState.compact);
        updateHomeViewToggleButton();
        await ensureHomeViewWindowSize(data.width, data.height);
    } catch (error) {
    }
}

async function ensureHomeViewWindowSize(width, height) {
    const targetWidth = Number(width);
    const targetHeight = Number(height);
    if (!Number.isFinite(targetWidth) || !Number.isFinite(targetHeight)) {
        return false;
    }

    for (let attempt = 0; attempt < 5; attempt += 1) {
        const resized = await resizeAppWindow(targetWidth, targetHeight);
        if (resized) {
            return true;
        }
        await new Promise((resolve) => setTimeout(resolve, 120));
    }

    return false;
}

async function setHomeCompactView(compact, { skipPersist = false } = {}) {
    homeViewState.compact = compact;
    document.body.classList.toggle('home-compact-view', compact);
    updateHomeViewToggleButton();

    if (compact) {
        switchTab('home');
    }

    let width = compact ? 490 : 550;
    let height = compact ? 225 : 440;

    if (!skipPersist) {
        try {
            const response = await fetch('/api/home-view', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ compact })
            });
            const data = await response.json();
            if (data.success) {
                width = data.width;
                height = data.height;
            }
        } catch (error) {
        }
    }

    homeViewState.width = width;
    homeViewState.height = height;

    await ensureHomeViewWindowSize(width, height);
}

function openAccountModal() {
    if (homeViewState.compact) {
        homeViewState.accountModalRestoreCompact = true;
        setHomeCompactView(false, { skipPersist: true });
    }

    const accountModal = document.getElementById('accountModal');
    if (accountModal) {
        accountModal.style.display = 'flex';
    }
}

function closeAccountModal() {
    const accountModal = document.getElementById('accountModal');
    if (accountModal) {
        accountModal.style.display = 'none';
    }

    if (homeViewState.accountModalRestoreCompact) {
        homeViewState.accountModalRestoreCompact = false;
        setHomeCompactView(true);
    }
}

async function toggleHomeCompactView() {
    await setHomeCompactView(!homeViewState.compact);
}

async function toggleHomeAlwaysOnTop() {
    const nextValue = !homeViewState.alwaysOnTop;
    await setAlwaysOnTop(nextValue);
}

async function preloadDetectedAppsForHome() {
    if (appState.detectedApps.apps.length) {
        await refreshHomeEditCurrentGameButton();
        return;
    }

    try {
        const data = await fetchDetectedAppsPayload();
        if (data.success) {
            setDetectedAppsState(data.apps || []);
        }
    } catch (error) {
    }

    await refreshHomeEditCurrentGameButton();
}

function detectedAppPathMatches(runningPath, savedPath) {
    const run = (runningPath || '').trim().toLowerCase();
    const saved = (savedPath || '').trim().toLowerCase();
    if (!run || !saved) {
        return false;
    }
    if (run === saved) {
        return true;
    }
    if (saved.includes('*') || saved.includes('?')) {
        const pattern = saved
            .replace(/[.+^${}()|[\]\\]/g, '\\$&')
            .replace(/\*/g, '.*')
            .replace(/\?/g, '.');
        return new RegExp(`^${pattern}$`, 'i').test(run);
    }
    return false;
}

function findDetectedAppForCurrentGame() {
    const category = (getCurrentCategory() || '').trim();
    if (!category) {
        return null;
    }

    const matching = (appState.detectedApps.apps || []).filter((app) =>
        (app.twitch_category || '').trim().toLowerCase() === category.toLowerCase()
    );
    if (!matching.length) {
        return null;
    }

    const processPath = (window.current_process_path || '').trim();
    if (processPath) {
        const pathMatch = matching.find((app) => detectedAppPathMatches(processPath, app.process_path));
        if (pathMatch) {
            return pathMatch;
        }
    }

    if (matching.length === 1) {
        return matching[0];
    }

    return null;
}

function updateHomeEditCurrentGameButton() {
    const btn = document.getElementById('homeEditCurrentGameBtn');
    if (!btn) {
        return;
    }

    const app = findDetectedAppForCurrentGame();
    btn.disabled = !app;
    btn.title = app ? `Edit ${app.app_name || app.twitch_category}` : 'Edit current game';
}

let homeEditButtonRefreshId = 0;

async function refreshHomeEditCurrentGameButton() {
    if (findDetectedAppForCurrentGame()) {
        updateHomeEditCurrentGameButton();
        return;
    }

    const category = (getCurrentCategory() || '').trim();
    if (!category) {
        updateHomeEditCurrentGameButton();
        return;
    }

    const refreshId = ++homeEditButtonRefreshId;
    try {
        const data = await fetchDetectedAppsPayload();
        if (refreshId !== homeEditButtonRefreshId) {
            return;
        }
        if (data.success) {
            appState.detectedApps.apps = sortDetectedAppsAlphabetically(data.apps || []);
        }
    } catch (error) {
    }

    if (refreshId !== homeEditButtonRefreshId) {
        return;
    }
    updateHomeEditCurrentGameButton();
}

async function openHomeEditCurrentGame() {
    let app = findDetectedAppForCurrentGame();

    if (!app && !appState.detectedApps.apps.length) {
        try {
            const data = await fetchDetectedAppsPayload();
            if (data.success) {
                setDetectedAppsState(data.apps || []);
            }
            app = findDetectedAppForCurrentGame();
        } catch (error) {
        }
    }

    if (!app) {
        showToast('Current category is not a saved game');
        updateHomeEditCurrentGameButton();
        return;
    }

    if (homeViewState.compact) {
        homeViewState.editGameRestoreCompact = true;
        await setHomeCompactView(false, { skipPersist: true });
    }

    showEditDialog(app);
}

function restoreHomeCompactAfterEditGame() {
    if (!homeViewState.editGameRestoreCompact) {
        return;
    }

    homeViewState.editGameRestoreCompact = false;
    setHomeCompactView(true);
}

async function switchToDefaultCategory() {
    try {
        const response = await fetch('/api/switch-default-category', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            showToast('Switched to default category');
        } else {
            showToast(data.error || 'Failed to switch to default category');
        }
    } catch (error) {
        showToast('Failed to switch to default category');
    }
}

async function applyDefaultStreamTitle() {
    try {
        const response = await fetch('/api/title-presets/apply-default', { method: 'POST' });
        const data = await response.json();
        if (data.success) {
            streamTitleUpdated(data);
            showToast('Default stream title applied');
            return;
        }
        showToast(data.error || 'Failed to apply default stream title');
    } catch (error) {
        showToast('Failed to apply default stream title');
    }
}

function setupHomeQuickActions() {
    const viewToggleBtn = document.getElementById('homeViewToggleBtn');
    const alwaysOnTopBtn = document.getElementById('homeAlwaysOnTopBtn');
    const defaultCategoryBtn = document.getElementById('homeDefaultCategoryBtn');
    const defaultTitleBtn = document.getElementById('homeDefaultTitleBtn');
    const editCurrentGameBtn = document.getElementById('homeEditCurrentGameBtn');

    if (viewToggleBtn) {
        viewToggleBtn.onclick = () => toggleHomeCompactView();
    }
    if (alwaysOnTopBtn) {
        alwaysOnTopBtn.onclick = () => toggleHomeAlwaysOnTop();
    }
    if (defaultCategoryBtn) {
        defaultCategoryBtn.onclick = () => switchToDefaultCategory();
    }
    if (defaultTitleBtn) {
        defaultTitleBtn.onclick = () => applyDefaultStreamTitle();
    }
    if (editCurrentGameBtn) {
        editCurrentGameBtn.onclick = () => openHomeEditCurrentGame();
    }

    updateHomeViewToggleButton();
    updateAlwaysOnTopButton();
    preloadDetectedAppsForHome();
}

function setupAccountAuth() {
    const welcomeLoginBtn = document.getElementById('welcome-login-btn');
    const welcomeStatus = document.getElementById('welcome-login-status');
    const accountModal = document.getElementById('accountModal');
    const accountModalClose = document.getElementById('accountModalClose');
    const addAccountBtn = document.getElementById('add-account-btn');

    if (welcomeLoginBtn) {
        welcomeLoginBtn.addEventListener('click', () => beginTwitchLogin(welcomeStatus, { forceVerify: true }));
    }

    if (elements.channelName) {
        elements.channelName.addEventListener('click', async () => {
            const status = await fetchAuthStatus();
            if (!status.authenticated) {
                showWelcomeScreen();
                return;
            }
            renderAccountList(status.accounts, status.active_login);
            openAccountModal();
        });
    }

    if (accountModalClose && accountModal) {
        accountModalClose.addEventListener('click', closeAccountModal);
        accountModal.addEventListener('click', (event) => {
            if (event.target === accountModal) {
                closeAccountModal();
            }
        });
    }

    if (addAccountBtn) {
        addAccountBtn.addEventListener('click', () => beginTwitchLogin(null, { forceVerify: true }));
    }
}

function accountAvatarUrl(account) {
    return account?.profile_image_url || '';
}

let appLoadingDepth = 0;
let offlineWaitCleanup = null;

async function checkInternetConnection() {
    try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 6000);
        const response = await fetch('/api/connectivity-check', {
            cache: 'no-store',
            signal: controller.signal,
        });
        clearTimeout(timeoutId);
        if (!response.ok) {
            return false;
        }
        const data = await response.json();
        return !!data.online;
    } catch (error) {
        return false;
    }
}

function showOfflineOverlay() {
    const overlay = document.getElementById('app-offline-overlay');
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.setAttribute('aria-hidden', 'false');
    }
    document.body.classList.add('app-offline-locked');
}

function hideOfflineOverlay() {
    const overlay = document.getElementById('app-offline-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        overlay.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('app-offline-locked');
}

function waitForInternetConnection() {
    if (offlineWaitCleanup) {
        offlineWaitCleanup();
        offlineWaitCleanup = null;
    }

    return new Promise((resolve) => {
        const retryBtn = document.getElementById('app-offline-retry-btn');
        let pollId = null;

        const cleanup = () => {
            if (pollId) {
                clearInterval(pollId);
                pollId = null;
            }
            window.removeEventListener('online', onOnline);
            if (retryBtn) {
                retryBtn.removeEventListener('click', onRetry);
            }
            offlineWaitCleanup = null;
        };

        const tryResolve = async () => {
            if (await checkInternetConnection()) {
                hideOfflineOverlay();
                cleanup();
                resolve();
            }
        };

        const onOnline = () => {
            tryResolve();
        };

        const onRetry = () => {
            tryResolve();
        };

        window.addEventListener('online', onOnline);
        if (retryBtn) {
            retryBtn.addEventListener('click', onRetry);
        }

        pollId = setInterval(tryResolve, 3000);
        offlineWaitCleanup = cleanup;
    });
}

async function ensureInternetAtStartup() {
    if (await checkInternetConnection()) {
        return;
    }

    hideAppLoading();
    showOfflineOverlay();
    await waitForInternetConnection();
    showAppLoading();
    document.body.classList.add('app-loading-locked');
    appLoadingDepth = Math.max(appLoadingDepth, 1);
}

function showAppLoading(message = 'Loading…') {
    appLoadingDepth += 1;
    const overlay = document.getElementById('app-loading-overlay');
    const messageEl = document.getElementById('app-loading-message');
    if (messageEl) {
        messageEl.textContent = message;
    }
    if (overlay) {
        overlay.classList.remove('hidden');
        overlay.setAttribute('aria-hidden', 'false');
    }
    document.body.classList.add('app-loading-locked');
}

function hideAppLoading() {
    appLoadingDepth = Math.max(0, appLoadingDepth - 1);
    if (appLoadingDepth > 0) {
        return;
    }
    const overlay = document.getElementById('app-loading-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
        overlay.setAttribute('aria-hidden', 'true');
    }
    document.body.classList.remove('app-loading-locked');
}

function renderAccountList(accounts, activeLogin) {
    const list = document.getElementById('account-list');
    if (!list) return;

    list.innerHTML = '';

    if (!accounts || accounts.length === 0) {
        list.innerHTML = '<div class="account-empty">No saved accounts yet.</div>';
        return;
    }

    accounts.forEach((account) => {
        const item = document.createElement('div');
        item.className = 'account-item' + (account.login === activeLogin ? ' active' : '');

        const main = document.createElement('div');
        main.className = 'account-item-main';

        const avatarWrap = document.createElement('div');
        avatarWrap.className = 'account-item-avatar-wrap';

        const avatar = document.createElement('img');
        avatar.className = 'account-item-avatar';
        avatar.alt = '';
        const avatarUrl = accountAvatarUrl(account);
        if (avatarUrl) {
            avatar.src = avatarUrl;
            avatar.onerror = () => {
                avatar.hidden = true;
            };
        } else {
            avatar.hidden = true;
        }

        const avatarFallback = document.createElement('div');
        avatarFallback.className = 'account-item-avatar-fallback';
        avatarFallback.textContent = (account.display_name || account.login || '?').charAt(0).toUpperCase();
        avatarWrap.appendChild(avatarFallback);
        avatarWrap.appendChild(avatar);
        main.appendChild(avatarWrap);

        const info = document.createElement('div');
        info.className = 'account-item-info';
        info.innerHTML = `
            <div class="account-item-name">${escapeHtml(account.display_name || account.login)}</div>
            <div class="account-item-login">@${escapeHtml(account.login)}</div>
        `;
        main.appendChild(info);

        const actions = document.createElement('div');
        actions.className = 'account-item-actions';

        if (account.login !== activeLogin) {
            const useBtn = document.createElement('button');
            useBtn.type = 'button';
            useBtn.textContent = 'Use';
            useBtn.addEventListener('click', () => switchAccount(account.login));
            actions.appendChild(useBtn);
        } else {
            const activeLabel = document.createElement('button');
            activeLabel.type = 'button';
            activeLabel.textContent = 'Active';
            activeLabel.disabled = true;
            actions.appendChild(activeLabel);
        }

        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'danger';
        removeBtn.textContent = 'Remove';
        removeBtn.addEventListener('click', () => removeAccount(account.login));
        actions.appendChild(removeBtn);

        item.appendChild(main);
        item.appendChild(actions);
        list.appendChild(item);
    });
}

async function switchAccount(login) {
    const account = appState.auth?.accounts?.find((entry) => entry.login === login);
    const displayName = account?.display_name || login;

    showAppLoading(`Switching to ${displayName}…`);

    try {
        const response = await fetch('/api/auth/switch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ login })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to switch account');
        }

        appState.auth = await fetchAuthStatus();
        renderAccountList(appState.auth.accounts, appState.auth.active_login);

        const streamInfo = await getStreamInfo();
        if (streamInfo) {
            updateUIWithStreamInfo(streamInfo);
            window.current_twitch_category = streamInfo.game_name;
        }

        const accountModal = document.getElementById('accountModal');
        if (accountModal) {
            closeAccountModal();
        }

        showToast(`Switched to ${data.user?.display_name || login}`);
    } catch (error) {
        showToast(error.message || 'Failed to switch account');
    } finally {
        hideAppLoading();
    }
}

async function removeAccount(login) {
    const account = appState.auth?.accounts?.find((entry) => entry.login === login);
    const displayName = account?.display_name || login;
    const message = `Remove <strong>${escapeHtml(displayName)}</strong> (@${escapeHtml(login)}) from CatSwitch? You will need to sign in again to use this account.`;

    showConfirmationModal(
        'Remove account',
        message,
        () => performRemoveAccount(login),
        null,
        'Remove'
    );
}

async function performRemoveAccount(login) {
    try {
        const response = await fetch('/api/auth/remove', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ login })
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to remove account');
        }

        appState.auth = await fetchAuthStatus();

        if (!appState.auth.authenticated) {
            document.getElementById('accountModal').style.display = 'none';
            homeViewState.accountModalRestoreCompact = false;
            showWelcomeScreen();
            return;
        }

        renderAccountList(appState.auth.accounts, appState.auth.active_login);

        const streamInfo = await getStreamInfo();
        if (streamInfo) {
            updateUIWithStreamInfo(streamInfo);
            window.current_twitch_category = streamInfo.game_name;
        } else {
            elements.channelName.textContent = appState.auth.user?.display_name || appState.auth.active_login;
        }

        showToast('Account removed');
    } catch (error) {
        showToast(error.message || 'Failed to remove account');
    }
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatPathTail(path, maxVisible = 44) {
    if (!path) return '';
    if (path.length <= maxVisible) return path;

    const sep = path.includes('\\') ? '\\' : '/';
    const tail = path.slice(-(maxVisible - 3));
    const sepIndex = tail.indexOf(sep);

    if (sepIndex > 0) {
        return '...' + tail.slice(sepIndex);
    }

    return '...' + tail;
}

function normalizeForSearch(text) {
    return String(text || '')
        .toLowerCase()
        .replace(/[-_/\\.,:;+()[\]{}|]+/g, ' ')
        .replace(/\s+/g, ' ')
        .trim();
}

function matchesSearchFilter(searchableText, filterQuery) {
    const normalizedQuery = normalizeForSearch(filterQuery);
    if (!normalizedQuery) return true;

    const normalizedText = normalizeForSearch(searchableText);
    const filterWords = normalizedQuery.split(' ').filter(Boolean);

    return filterWords.every((word) => normalizedText.includes(word));
}

function setupEventListeners() {
    // Toggle category lock
    if (elements.categoryLock) {
        elements.categoryLock.addEventListener('click', function(e) {
            e.stopPropagation();
            toggleCategoryLock();
        });
    }

    // Toggle title lock
    if (elements.titleLock) {
        elements.titleLock.addEventListener('click', function(e) {
            e.stopPropagation();
            toggleTitleLock();
        });
    }

    // Show category search when clicking on category text
    if (elements.categoryLabel) {
        elements.categoryLabel.addEventListener('click', showCategorySearch);
    }

    // Handle category search input
    elements.categorySearch.addEventListener('input', debounce(handleCategorySearch, 300));
    elements.categorySearch.addEventListener('keydown', handleCategorySearchKeydown);
    elements.categoryInput.addEventListener('click', function(e) {
        e.stopPropagation(); // Prevent click from propagating to document
    });
    
    // Add mouse event listeners to detect mouse navigation
    if (elements.categorySearchResults) {
        elements.categorySearchResults.addEventListener('mouseenter', () => {
            // Switch back to mouse navigation
            elements.categorySearchResults.dataset.keyboardNav = 'false';
            // Clear any keyboard selection
            const items = elements.categorySearchResults.querySelectorAll('.search-result-item');
            items.forEach(item => item.classList.remove('selected'));
        });
    }

    // Show title edit when clicking on title
    if (elements.titleLabel) {
        elements.titleLabel.addEventListener('click', showTitleEdit);
    }

    // Handle title input
    elements.titleInput.addEventListener('keydown', handleTitleInputKeydown);
    elements.titleInput.addEventListener('click', function(e) {
        e.stopPropagation(); // Prevent click from propagating to document
    });

    // Add click handlers to edit containers to prevent propagation
    elements.categoryEditContainer.addEventListener('click', function(e) {
        e.stopPropagation();
    });
    
    elements.titleEditContainer.addEventListener('click', function(e) {
        e.stopPropagation();
    });

    // Close dropdowns when clicking outside
    document.addEventListener('click', (e) => {
        // For category edit
        if (!elements.categoryContainer.contains(e.target) && 
            !elements.categoryEditContainer.contains(e.target) &&
            !elements.categorySearchResults.contains(e.target)) {
            hideCategorySearch();
        }
        
        // For title edit
        if (!elements.titleContainer.contains(e.target) &&
            !elements.titleEditContainer.contains(e.target) &&
            !(elements.titleLock && elements.titleLock.contains(e.target))) {
            hideTitleEdit();
        }
    });

    // Note: Enter key handling is now done in handleCategorySearchKeydown with validation

    // Setup modal buttons
    setupModalButtons();
}

async function toggleCategoryLock() {
    const isLocked = !appState.categoryLocked;
    
    try {
        updateCategoryLockDisplay(isLocked);
        
        const response = await fetchData('toggle-lock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                locked: isLocked
            })
        });
        
        if (response && response.success) {
            appState.categoryLocked = response.locked;
            updateCategoryLockDisplay(response.locked);

            if (response.current_category) {
                document.getElementById('current-category').textContent = response.current_category;

                if (response.box_art_url) {
                    updateCategoryImage(response.box_art_url);
                }
            }
        } else {
            if (response && response.locked !== undefined) {
                updateCategoryLockDisplay(response.locked);
            } else {
                updateCategoryLockDisplay(!isLocked);
            }

            showToast('Failed to toggle category lock');
        }
    } catch (error) {
        updateCategoryLockDisplay(!isLocked);
        showToast('Error toggling category lock');
    }
}

async function toggleTitleLock() {
    const isLocked = !appState.titleLocked;

    try {
        updateTitleLockDisplay(isLocked);

        const response = await fetchData('toggle-title-lock', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                locked: isLocked
            })
        });

        if (response && response.success) {
            appState.titleLocked = response.title_locked;
            updateTitleLockDisplay(response.title_locked);
        } else {
            if (response && response.title_locked !== undefined) {
                updateTitleLockDisplay(response.title_locked);
            } else {
                updateTitleLockDisplay(!isLocked);
            }

            showToast('Failed to toggle title lock');
        }
    } catch (error) {
        updateTitleLockDisplay(!isLocked);
        showToast('Error toggling title lock');
    }
}

function showCategorySearch() {
    // Get the most up-to-date category name before showing the edit field
    const currentTwitchCategory = getCurrentCategory();
    
    // Show the edit field
    elements.categoryContainer.classList.add('hidden');
    elements.categoryEditContainer.classList.remove('hidden');
    
    // Set the input value to the current category
    elements.categoryInput.value = currentTwitchCategory || '';
    
    // Focus and select the input
    elements.categoryInput.focus();
    elements.categoryInput.select();
}

// Helper function to get the most up-to-date category across all sources
function getCurrentCategory() {
    if (window.current_twitch_category) {
        return window.current_twitch_category;
    }
    if (appState.fullCategoryName) {
        return appState.fullCategoryName;
    }
    if (appState.currentCategory) {
        return appState.currentCategory;
    }
    if (elements.categoryLabel && elements.categoryLabel.textContent) {
        return elements.categoryLabel.textContent;
    }
    return '';
}

function hideCategorySearch() {
    elements.categoryEditContainer.classList.add('hidden');
    elements.categoryContainer.classList.remove('hidden');
    elements.categorySearchResults.innerHTML = '';
}

function handleCategorySearch() {
    const query = elements.categoryInput.value.trim();
    if (query.length < 2) {
        clearCategoryResults();
        return;
    }
    
    searchCategories(query);
}

function renderCategoryResults(categories) {
    elements.categorySearchResults.innerHTML = '';
    
    categories.forEach(category => {
        const resultItem = document.createElement('div');
        resultItem.classList.add('search-result-item');
        // Handle both string and object formats
        const categoryName = typeof category === 'string' ? category : category.name;
        resultItem.textContent = categoryName;
        resultItem.addEventListener('click', () => {
            // Clear keyboard navigation state since we're using mouse
            elements.categorySearchResults.dataset.keyboardNav = 'false';
            // Remove any existing selections
            elements.categorySearchResults.querySelectorAll('.search-result-item').forEach(item => item.classList.remove('selected'));
            // Add selected class to clicked item
            resultItem.classList.add('selected');
            selectCategoryDirectly(categoryName);
        });
        elements.categorySearchResults.appendChild(resultItem);
    });
}

async function selectCategory(category) {
    hideCategorySearch();
    
    // Don't immediately update the UI, wait for the API response
    // This prevents showing the search query before we get the official name
    
    // No toast message for starting the update
    
    // Update on server
    updateCategory(category);
}

async function selectCategoryDirectly(category) {
    // This function is for direct selection (from dropdown) - no validation needed
    hideCategorySearch();
    
    // Don't immediately update the UI, wait for the API response
    // This prevents showing the search query before we get the official name
    
    // No toast message for starting the update
    
    // Update on server
    updateCategory(category);
}

function handleCategorySearchKeydown(e) {
    if (e.key === 'Enter') {
        e.preventDefault();
        const query = elements.categoryInput.value.trim();
        const selectedItem = document.querySelector('.search-result-item.selected');
        
        if (selectedItem) {
            // Category is selected from dropdown, use it directly without validation
            const categoryName = selectedItem.textContent.trim();
            elements.categoryInput.value = categoryName;
            elements.categorySearchResults.innerHTML = '';
            selectCategoryDirectly(categoryName);
        } else if (query) {
            // No category selected, validate and select
            validateAndSelectCategory(query);
        }
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        navigateHomeCategoryDropdown('down');
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        navigateHomeCategoryDropdown('up');
    } else if (e.key === 'Escape') {
        hideCategorySearch();
    }
}

function validateAndSelectCategory(category) {
    
    // Check if this is a manually entered category (not selected from dropdown)
    const selectedItem = document.querySelector('.search-result-item.selected');
    if (selectedItem) {
        // Category was selected from dropdown, use it directly without validation
        const categoryName = selectedItem.textContent.trim();
        selectCategoryDirectly(categoryName);
        return;
    }
    
    // Only validate if this is a manually entered category
    fetch(`/api/categories?query=${encodeURIComponent(category)}`)
        .then(response => response.json())
        .then(categories => {
            if (categories && categories.length > 0) {
                // Find exact match (case-insensitive)
                const exactMatch = categories.find(cat => {
                    const catName = typeof cat === 'string' ? cat : cat.name;
                    return catName.toLowerCase() === category.toLowerCase();
                });
                
                if (exactMatch) {
                    const categoryName = typeof exactMatch === 'string' ? exactMatch : exactMatch.name;
                    // Use the exact match from Twitch (with correct casing)
                    selectCategoryDirectly(categoryName);
                } else {
                    showToast('Please enter a valid Twitch category or select one from the dropdown');
                    // Don't call selectCategory() - this prevents the "failed to update" toast
                    // Keep the input field open so user can fix their input
                }
            } else {
                showToast('Please enter a valid Twitch category or select one from the dropdown');
                // Don't call selectCategory() - this prevents the "failed to update" toast
                // Keep the input field open so user can fix their input
            }
        })
        .catch(error => {
            showToast('Failed to validate category. Please try again.');
            // Don't call selectCategory() - this prevents the "failed to update" toast
            // Keep the input field open so user can fix their input
        });
}

function navigateHomeCategoryDropdown(direction) {
    // Try both possible results containers
    let homeResults = elements.categorySearchResults;
    if (!homeResults) {
        homeResults = document.getElementById('category-results');
    }
    if (!homeResults) return;
    
    const items = homeResults.querySelectorAll('.search-result-item');
    if (items.length === 0) return;
    
    // Mark that we're using keyboard navigation
    homeResults.dataset.keyboardNav = 'true';
    
    const currentSelected = homeResults.querySelector('.search-result-item.selected');
    let newIndex = -1;
    
    if (currentSelected) {
        // Find current index
        for (let i = 0; i < items.length; i++) {
            if (items[i] === currentSelected) {
                if (direction === 'down') {
                    newIndex = (i + 1) % items.length;
                } else {
                    newIndex = i === 0 ? items.length - 1 : i - 1;
                }
                break;
            }
        }
    } else {
        // No current selection, select first item
        newIndex = direction === 'down' ? 0 : items.length - 1;
    }
    
    // Remove previous selection
    items.forEach(item => item.classList.remove('selected'));
    
    // Add new selection
    if (newIndex >= 0 && newIndex < items.length) {
        items[newIndex].classList.add('selected');
        
        // Scroll into view if needed
        items[newIndex].scrollIntoView({ 
            block: 'nearest', 
            behavior: 'smooth' 
        });
        
        // Update the input field with the selected category
        const categoryName = items[newIndex].textContent.trim();
        // Try both possible input fields
        if (elements.categoryInput) {
            elements.categoryInput.value = categoryName;
        }
        const categorySearch = document.getElementById('category-search');
        if (categorySearch) {
            categorySearch.value = categoryName;
        }
    }
}

function showTitleEdit() {
    elements.titleContainer.classList.add('hidden');
    elements.titleEditContainer.classList.remove('hidden');
    elements.titleInput.value = appState.titleTemplate || appState.currentTitle || '';
    elements.titleInput.focus();
    elements.titleInput.select();
}

function hideTitleEdit() {
    elements.titleEditContainer.classList.add('hidden');
    elements.titleContainer.classList.remove('hidden');
}

async function handleTitleUpdate() {
    const newTitle = elements.titleInput.value.trim();
    if (!newTitle) return;
    
    hideTitleEdit();
    
    // Update on server (%cat resolved server-side)
    const result = await updateTitle(newTitle);
    if (!result || !result.success) {
        showToast('Failed to update stream title');
        return;
    }

    const resolvedTitle = result.resolved_title || resolveTitleText(newTitle, getCurrentCategory());
    setStreamTitleState(result.title_template || newTitle, resolvedTitle);

    if (result.lock_applied) {
        appState.titleLocked = true;
        updateTitleLockDisplay(true);
        showToast('Manual title set - Automatic updates have been locked');
    } else if (
        !appState.titleLocked
        && appState.detectionSettings.auto_lock_title_on_manual_update
    ) {
        toggleTitleLock();
        showToast('Manual title set - Automatic updates have been locked');
    }
}

function handleTitleInputKeydown(e) {
    if (e.key === 'Enter') {
        handleTitleUpdate();
    } else if (e.key === 'Escape') {
        hideTitleEdit();
    }
}

function updateUIWithStreamInfo(streamInfo) {
    appState.streamInfo = streamInfo;
    
    if (streamInfo.broadcaster_name) {
        elements.channelName.textContent = truncateText(streamInfo.broadcaster_name, 35);
    }
    
    if (streamInfo.title_template !== undefined || streamInfo.title) {
        const template = streamInfo.title_template ?? streamInfo.title;
        const category = streamInfo.game_name || getCurrentCategory();
        const resolved = streamInfo.title ?? resolveTitleText(template, category);
        setStreamTitleState(template, resolved);
    }
    
    if (streamInfo.game_name) {
        // Update all category storage locations
        appState.currentCategory = streamInfo.game_name;
        appState.fullCategoryName = streamInfo.game_name; // Store the full name
        window.current_twitch_category = streamInfo.game_name; // Also store in global variable
        
        // Update UI
        elements.categoryLabel.textContent = streamInfo.game_name;
        
        // Also update category input if it exists
        if (elements.categoryInput) {
            elements.categoryInput.value = streamInfo.game_name;
        }
    }
    
    if (streamInfo.box_art_url) {
        updateCategoryImage(streamInfo.box_art_url);
    }

    refreshHomeEditCurrentGameButton();
}

function updateCategoryImage(boxArtUrl) {
    setBoxArtImage(elements.categoryImage, boxArtUrl);
}

function truncateText(text, maxLength) {
    if (!text) return '';
    if (text.length <= maxLength) return text;
    return text.substring(0, maxLength - 3) + '...';
}

function isCategoryLocked() {
    return appState.categoryLocked;
}

function startGameDetection() {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource('/api/game-detection');
    
    eventSource.onmessage = function(event) {
        try {
            const data = JSON.parse(event.data);
            console.log('Game detection event:', data);
            
            const gameName = data.game_name || data.game;
            if (gameName && !isCategoryLocked()) {
                gameDetected(
                    gameName,
                    data.box_art_url,
                    Boolean(data.is_manual),
                    false
                );
            }

            if (data.is_locked !== undefined) {
                updateCategoryLockDisplay(data.is_locked);
            }
            if (data.title_locked !== undefined) {
                updateTitleLockDisplay(data.title_locked);
            }
        } catch (error) {
            console.error('Error processing game detection message:', error);
            try {
                console.error('Raw event data:', event.data);
            } catch (loggingError) {
                console.error('Could not log raw event data');
            }
        }
    };
    
    eventSource.onerror = function(error) {
        console.error('Game detection event source error:', error);
        if (eventSource) {
            eventSource.close();
            eventSource = null;
        }
        setTimeout(() => {
            console.log('Reconnecting game detection...');
            startGameDetection();
        }, 3000);
    };
}

function updateUIWithGameInfo(data) {
    // Always update the current category display
    document.getElementById('current-category').textContent = data.game_name;
    
    // Update lock status if provided
    if (data.is_locked !== undefined) {
        appState.categoryLocked = data.is_locked;
        updateCategoryLockDisplay(data.is_locked);
    }
    if (data.title_locked !== undefined) {
        appState.titleLocked = data.title_locked;
        updateTitleLockDisplay(data.title_locked);
    }
    
    // Update the box art if provided
    if (data.box_art_url) {
        updateCategoryImage(data.box_art_url);
    }

    refreshHomeEditCurrentGameButton();
    refreshTitleDisplay();
}

function updateCategoryLockDisplay(isLocked) {
    const lockIcon = document.getElementById('category-lock');
    if (!lockIcon) {
        console.error('Category lock icon element not found');
        return;
    }

    appState.categoryLocked = isLocked;

    if (isLocked) {
        lockIcon.classList.remove('unlocked');
        lockIcon.classList.add('locked');
        lockIcon.title = 'Enable automatic category updates';
    } else {
        lockIcon.classList.remove('locked');
        lockIcon.classList.add('unlocked');
        lockIcon.title = 'Disable automatic category updates';
    }
}

function updateTitleLockDisplay(isLocked) {
    const lockIcon = document.getElementById('title-lock');
    if (!lockIcon) {
        console.error('Title lock icon element not found');
        return;
    }

    appState.titleLocked = isLocked;

    if (isLocked) {
        lockIcon.classList.remove('unlocked');
        lockIcon.classList.add('locked');
        lockIcon.title = 'Enable automatic title updates';
    } else {
        lockIcon.classList.remove('locked');
        lockIcon.classList.add('unlocked');
        lockIcon.title = 'Disable automatic title updates';
    }
}

function showToast(message, duration = 3000) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.remove('hidden');
    toast.classList.add('visible');
    
    setTimeout(() => {
        toast.classList.remove('visible');
        toast.classList.add('hidden');
    }, duration);
}

// Helper function for debouncing
function debounce(func, wait) {
    let timeout;
    const debounced = function(...args) {
        clearTimeout(timeout);
        timeout = setTimeout(() => func.apply(this, args), wait);
    };
    debounced.cancel = function() {
        clearTimeout(timeout);
        timeout = null;
    };
    return debounced;
}

// Semicolon-delimited list file fields. Mirrors catswitch/list_format.py.
const LIST_FIELD_SEP = ';';

function escapeListField(value) {
    const text = String(value ?? '');
    let result = '';
    for (const ch of text) {
        if (ch === '\\') {
            result += '\\\\';
        } else if (ch === LIST_FIELD_SEP) {
            result += '\\;';
        } else {
            result += ch;
        }
    }
    return result;
}

function splitListFields(line, maxSplits = -1) {
    const parts = [];
    let current = '';
    let splits = 0;

    for (let i = 0; i < line.length; i++) {
        const ch = line[i];
        if (ch === '\\' && i + 1 < line.length) {
            const next = line[i + 1];
            if (next === ';') {
                current += ';';
                i += 1;
                continue;
            }
            if (next === '\\') {
                current += '\\';
                i += 1;
                continue;
            }
        }
        if (ch === LIST_FIELD_SEP && (maxSplits < 0 || splits < maxSplits)) {
            parts.push(current);
            current = '';
            splits += 1;
            continue;
        }
        current += ch;
    }

    parts.push(current);
    return parts;
}

function joinListFields(...fields) {
    return fields.map(escapeListField).join(LIST_FIELD_SEP);
}

// Window-title fields can hold multiple titles separated by unescaped pipes.
// Mirrors split_window_titles/join_window_titles in list_format.py.
function splitWindowTitles(field) {
    if (!field) return [];
    const titles = [];
    let current = '';
    for (let i = 0; i < field.length; i++) {
        const ch = field[i];
        if (ch === '\\' && i + 1 < field.length) {
            const nxt = field[i + 1];
            if (nxt === '|' || nxt === '\\') {
                current += nxt;
                i++;
                continue;
            }
        }
        if (ch === '|') {
            titles.push(current);
            current = '';
            continue;
        }
        current += ch;
    }
    titles.push(current);
    return titles.map(t => t.trim()).filter(t => t.length > 0);
}

function joinWindowTitles(titles) {
    return (titles || [])
        .map(t => String(t || '').trim())
        .filter(t => t.length > 0)
        .map(t => t.replace(/\\/g, '\\\\').replace(/\|/g, '\\|'))
        .join('|');
}

const WINDOW_TITLE_SAVE_BUTTONS = {
    'edit-window-title-list': 'saveCategoryBtn',
    'add-window-title-list': 'saveAddCategoryBtn'
};

function addWindowTitleRow(containerId, value = '') {
    const container = document.getElementById(containerId);
    if (!container) return null;

    const row = document.createElement('div');
    row.className = 'window-title-row window-title-row-extra';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'form-input window-title-input';
    input.placeholder = 'Enter window title...';
    input.value = value;
    // onkeydown (not addEventListener) so the modal setup loops can overwrite it
    // without stacking a second Enter handler on the same input
    input.onkeydown = (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            const saveBtn = document.getElementById(WINDOW_TITLE_SAVE_BUTTONS[containerId]);
            if (saveBtn) saveBtn.click();
        }
    };

    const removeBtn = document.createElement('button');
    removeBtn.type = 'button';
    removeBtn.className = 'btn btn-secondary window-title-remove-btn';
    removeBtn.title = 'Remove this window title';
    removeBtn.innerHTML = '<span class="icon icon-minus icon-sm" aria-hidden="true"></span>';
    removeBtn.onclick = () => row.remove();

    row.appendChild(input);
    row.appendChild(removeBtn);
    container.appendChild(row);
    return input;
}

function populateWindowTitleInputs(containerId, field) {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.querySelectorAll('.window-title-row-extra').forEach(row => row.remove());

    const titles = splitWindowTitles(field);
    const primaryInput = container.querySelector('.window-title-input');
    if (primaryInput) {
        primaryInput.value = titles[0] || '';
    }
    titles.slice(1).forEach(title => addWindowTitleRow(containerId, title));
}

function collectWindowTitles(containerId) {
    const container = document.getElementById(containerId);
    if (!container) return '';

    const titles = Array.from(container.querySelectorAll('.window-title-input'))
        .map(input => input.value);
    return joinWindowTitles(titles);
}

function setupWindowTitleAddButton(buttonId, containerId) {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.onclick = () => {
        const input = addWindowTitleRow(containerId);
        if (input) {
            input.scrollIntoView({ block: 'nearest' });
            input.focus();
        }
    };
}

// Category dropdowns in the Add/Edit App modals use position:fixed so they can
// overlay the scrollable modal body. JS anchors them to their input.
const CATEGORY_DROPDOWN_PAIRS = [
    ['edit-category-input', 'edit-category-results'],
    ['addCategoryName', 'add-category-results']
];

function positionCategoryDropdown(inputId, resultsId) {
    const input = document.getElementById(inputId);
    const results = document.getElementById(resultsId);
    if (!input || !results) return;

    const rect = input.getBoundingClientRect();
    results.style.top = `${rect.bottom}px`;
    results.style.left = `${rect.left}px`;
    results.style.width = `${rect.width}px`;
}

function repositionCategoryDropdowns() {
    for (const [inputId, resultsId] of CATEGORY_DROPDOWN_PAIRS) {
        const results = document.getElementById(resultsId);
        if (results && results.childElementCount > 0) {
            positionCategoryDropdown(inputId, resultsId);
        }
    }
}

window.addEventListener('scroll', repositionCategoryDropdowns, true);
window.addEventListener('resize', repositionCategoryDropdowns);

function setupHelpIconTooltips() {
    let tooltipEl = document.getElementById('help-tooltip');
    if (!tooltipEl) {
        tooltipEl = document.createElement('div');
        tooltipEl.id = 'help-tooltip';
        tooltipEl.className = 'help-tooltip hidden';
        tooltipEl.setAttribute('role', 'tooltip');
        document.body.appendChild(tooltipEl);
    }

    let activeIcon = null;
    let hideTimer = null;

    const hideHelpTooltip = () => {
        clearTimeout(hideTimer);
        activeIcon = null;
        tooltipEl.classList.add('hidden');
    };

    const positionHelpTooltip = (icon) => {
        const rect = icon.getBoundingClientRect();
        const gap = 6;

        tooltipEl.classList.remove('hidden');
        const tipRect = tooltipEl.getBoundingClientRect();

        let top = rect.bottom + gap;
        let left = rect.left;

        if (top + tipRect.height > window.innerHeight - 8) {
            top = rect.top - tipRect.height - gap;
        }
        if (left + tipRect.width > window.innerWidth - 8) {
            left = Math.max(8, window.innerWidth - tipRect.width - 8);
        }

        tooltipEl.style.left = `${left}px`;
        tooltipEl.style.top = `${top}px`;
    };

    const showHelpTooltip = (icon) => {
        const text = icon.getAttribute('data-tooltip');
        if (!text) {
            return;
        }

        clearTimeout(hideTimer);
        activeIcon = icon;
        tooltipEl.textContent = text;
        positionHelpTooltip(icon);
    };

    const scheduleHideHelpTooltip = () => {
        clearTimeout(hideTimer);
        hideTimer = setTimeout(hideHelpTooltip, 120);
    };

    document.addEventListener('mousedown', (event) => {
        if (event.target.closest('.help-icon[data-tooltip]')) {
            event.preventDefault();
            event.stopPropagation();
        }
    }, true);

    document.addEventListener('click', (event) => {
        const icon = event.target.closest('.help-icon[data-tooltip]');
        if (icon) {
            event.preventDefault();
            event.stopPropagation();
            if (activeIcon === icon && !tooltipEl.classList.contains('hidden')) {
                hideHelpTooltip();
            } else {
                showHelpTooltip(icon);
            }
            return;
        }

        if (!tooltipEl.classList.contains('hidden') && !event.target.closest('#help-tooltip')) {
            hideHelpTooltip();
        }
    });

    document.addEventListener('mouseover', (event) => {
        const icon = event.target.closest('.help-icon[data-tooltip]');
        if (icon) {
            showHelpTooltip(icon);
        }
    });

    document.addEventListener('mouseout', (event) => {
        const icon = event.target.closest('.help-icon[data-tooltip]');
        if (!icon) {
            return;
        }

        const nextTarget = event.relatedTarget;
        if (nextTarget && (icon.contains(nextTarget) || tooltipEl.contains(nextTarget))) {
            return;
        }

        scheduleHideHelpTooltip();
    });

    tooltipEl.addEventListener('mouseenter', () => clearTimeout(hideTimer));
    tooltipEl.addEventListener('mouseleave', scheduleHideHelpTooltip);

    const repositionActiveTooltip = () => {
        if (activeIcon && !tooltipEl.classList.contains('hidden')) {
            positionHelpTooltip(activeIcon);
        }
    };

    window.addEventListener('resize', repositionActiveTooltip);
    window.addEventListener('scroll', repositionActiveTooltip, true);
}

function setupWindowDragging() {
    
    if (!elements.titleBar) {
        return;
    }
    
    // Use native window-drag functionality via data attribute
    elements.titleBar.setAttribute('data-pywebview-drag-region', '');
    
    // No need for the manual dragging listeners, as the native functionality will handle it
}

function showCategoryInterface() {
    document.getElementById('category-interface').classList.add('visible');
    document.getElementById('category-search').focus();
    
    // Clear previous search results
    document.getElementById('category-results').innerHTML = '';
    
    // Set up search input event listener (with debounce)
    const searchInput = document.getElementById('category-search');
    searchInput.addEventListener('input', debounce(function(e) {
        const query = e.target.value.trim();
        if (query.length >= 2) {
            searchCategories(query);
        } else {
            document.getElementById('category-results').innerHTML = '';
        }
    }, 500));
    
    // Add event listener for the close button
    document.getElementById('category-close').addEventListener('click', hideCategoryInterface);
    
    // Add event listener for the Enter key with keyboard navigation
    searchInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            const query = searchInput.value.trim();
            const selectedItem = document.querySelector('.search-result-item.selected');
            
            if (selectedItem) {
                // Category is selected from dropdown, use it directly without validation
                const categoryName = selectedItem.textContent.trim();
                searchInput.value = categoryName;
                document.getElementById('category-results').innerHTML = '';
                selectCategoryDirectly(categoryName);
            } else if (query) {
                // No category selected, validate and select
                validateAndSelectCategory(query);
            }
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            navigateHomeCategoryDropdown('down');
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            navigateHomeCategoryDropdown('up');
        } else if (e.key === 'Escape') {
            hideCategoryInterface();
        }
    });
    
    // Add mouse event listeners to detect mouse navigation
    const categoryResults = document.getElementById('category-results');
    if (categoryResults) {
        categoryResults.addEventListener('mouseenter', () => {
            // Switch back to mouse navigation
            categoryResults.dataset.keyboardNav = 'false';
            // Clear any keyboard selection
            const items = categoryResults.querySelectorAll('.search-result-item');
            items.forEach(item => item.classList.remove('selected'));
        });
    }
}

function hideCategoryInterface() {
    document.getElementById('category-interface').classList.remove('visible');
    
    // Remove event listeners
    document.getElementById('category-search').value = '';
    document.getElementById('category-results').innerHTML = '';
}

// Add this function to handle game detection updates from Python
function gameDetected(gameName, boxArtUrl, isManual, isExistingMatch = false) {
    if (!gameName) return;
    
    // Prevent duplicate calls in quick succession
    const now = Date.now();
    if (window._lastGameDetectedTime && (now - window._lastGameDetectedTime < 200)) {
        console.log('Skipping duplicate gameDetected call');
        return;
    }
    window._lastGameDetectedTime = now;
    
    console.log(`Game detected: ${gameName}, box art: ${boxArtUrl}, manual: ${isManual}`);
    
    // Store the full category name in various places to ensure it's available
    // 1. In the app state
    if (window.appState) {
        window.appState.fullCategoryName = gameName;
        window.appState.currentCategory = gameName;
    }
    
    // 2. In a global variable for access from any context
    window.current_twitch_category = gameName;
    console.log('Set window.current_twitch_category to:', gameName);
    
    // Update all game name elements in the UI
    // 1. The current-category element (main display)
    let gameNameElement = document.getElementById('current-category');
    if (gameNameElement) {
        gameNameElement.textContent = gameName;
    }
    
    // 2. The category-label element (if exists)
    let categoryLabel = document.getElementById('category-label');
    if (categoryLabel) {
        categoryLabel.textContent = truncateText(gameName, 27);
    }
    
    // 3. The current-game element (if exists)
    let currentGame = document.getElementById('current-game');
    if (currentGame) {
        currentGame.textContent = truncateText(gameName, 27);
    }
    
    // Always update the category input field even if it's hidden
    // This ensures when the edit mode is shown later, it has the correct value
    let categoryInput = document.getElementById('category-input');
    if (categoryInput) {
        categoryInput.value = gameName; // Use full name in input field
    }
    
    // Also update the category search field if it exists
    let categorySearch = document.getElementById('category-search');
    if (categorySearch) {
        categorySearch.value = gameName; // Use full name in search field
    }
    
    // Update the box art if provided
    const categoryImage = document.getElementById('category-image');
    if (categoryImage) {
        if (boxArtUrl && boxArtUrl !== 'undefined' && boxArtUrl !== 'null') {
            setBoxArtImage(categoryImage, boxArtUrl);
        } else {
            setBoxArtImage(categoryImage, '');
        }
    }
    
    // Auto-save of fresh detections (including window titles) happens on the backend
    // via record_detection_result — no frontend save needed here.
    refreshHomeEditCurrentGameButton();
    refreshTitleDisplay();
}

let settingsCategorySaveTimer = null;
let settingsDelaySaveTimer = null;
const USER_THEME_STYLESHEET_ID = 'user-theme-stylesheet';

function normalizeThemeFilename(theme) {
    const value = (theme || 'Default.css').trim() || 'Default.css';
    return value.toLowerCase() === 'default' ? 'Default.css' : value;
}

function applyTheme(theme) {
    const filename = normalizeThemeFilename(theme);
    appState.theme = filename;

    let link = document.getElementById(USER_THEME_STYLESHEET_ID);
    if (!link) {
        link = document.createElement('link');
        link.id = USER_THEME_STYLESHEET_ID;
        link.rel = 'stylesheet';
        document.head.appendChild(link);
    }

    link.href = `/api/themes/css?file=${encodeURIComponent(filename)}&t=${Date.now()}`;
}

function populateThemeSelect(themes, selectedTheme) {
    const select = elements.settingsTheme;
    if (!select) return;

    const currentValue = normalizeThemeFilename(selectedTheme || appState.theme);
    select.innerHTML = '';

    (themes || []).forEach((theme) => {
        const option = document.createElement('option');
        option.value = theme.value;
        option.textContent = theme.label;
        select.appendChild(option);
    });

    const hasCurrent = Array.from(select.options).some((option) => option.value === currentValue);
    select.value = hasCurrent ? currentValue : 'Default.css';
}

async function refreshThemeOptions() {
    try {
        const response = await fetch('/api/themes/list');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        populateThemeSelect(data.themes || [], appState.theme);
    } catch (error) {
    }
}

async function loadAndApplyTheme() {
    try {
        const [settingsResponse, listResponse] = await Promise.all([
            fetch('/api/settings/theme'),
            fetch('/api/themes/list'),
        ]);
        if (!settingsResponse.ok) {
            throw new Error(`HTTP ${settingsResponse.status}`);
        }
        const data = await settingsResponse.json();
        const theme = normalizeThemeFilename(data.theme || 'Default.css');
        applyTheme(theme);

        if (listResponse.ok) {
            const listData = await listResponse.json();
            populateThemeSelect(listData.themes || [], theme);
        } else {
            populateThemeSelect([{ value: 'Default.css', label: 'Default' }], theme);
        }
    } catch (error) {
        applyTheme('Default.css');
    }
}

async function saveThemeSelection(theme, { silent = true } = {}) {
    try {
        const response = await fetch('/api/settings/theme', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ theme }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to save theme');
        }
        applyTheme(data.theme || 'Default.css');
        if (!silent) {
            showToast('Theme applied');
        }
        return true;
    } catch (error) {
        showToast('Failed to save theme');
        return false;
    }
}

function openThemesFolder() {
    fetch('/api/themes/open-folder')
        .then((response) => response.json())
        .then((result) => {
            if (!result.success) {
                showToast(result.error || 'Failed to open folder');
            }
        })
        .catch((error) => {
            showToast('Failed to open folder');
        });
}

const AUTO_EXCLUDED_APPS_LIST_NAME = 'Auto-excluded apps';
const AUTO_EXCLUSION_DISABLED_TOAST = 'App auto-exclusion disabled';

function isAutoExcludedAppsList(listInfo) {
    return Boolean(listInfo && listInfo.name === AUTO_EXCLUDED_APPS_LIST_NAME);
}

function applyDetectionSettingsToForm(settings) {
    if (!settings) return;

    appState.detectionSettings = {
        default_category: settings.default_category || 'Just Chatting',
        switch_delay_seconds: Number(settings.switch_delay_seconds ?? 0),
        auto_lock_category_on_manual_update: settings.auto_lock_category_on_manual_update !== false,
        auto_lock_title_on_manual_update: settings.auto_lock_title_on_manual_update !== false,
        use_discord_detectable: settings.use_discord_detectable !== false,
    };

    if (elements.settingsDefaultCategory) {
        elements.settingsDefaultCategory.value = appState.detectionSettings.default_category;
    }
    if (elements.settingsSwitchDelay) {
        elements.settingsSwitchDelay.value = appState.detectionSettings.switch_delay_seconds;
    }
    if (elements.settingsAutoLockCategory) {
        elements.settingsAutoLockCategory.checked = appState.detectionSettings.auto_lock_category_on_manual_update;
    }
    if (elements.settingsAutoLockTitle) {
        elements.settingsAutoLockTitle.checked = appState.detectionSettings.auto_lock_title_on_manual_update;
    }
    if (elements.settingsUseDiscordDetectable) {
        elements.settingsUseDiscordDetectable.checked = appState.detectionSettings.use_discord_detectable;
    }

    const defaultCategoryBtn = document.getElementById('homeDefaultCategoryBtn');
    if (defaultCategoryBtn) {
        defaultCategoryBtn.title = `Switch to default category (${appState.detectionSettings.default_category})`;
    }
}

async function loadDetectionSettings() {
    try {
        const response = await fetch('/api/settings/detection');
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}`);
        }
        const settings = await response.json();
        applyDetectionSettingsToForm(settings);
        if (settings.discord_disabled_notice) {
            showToast(settings.discord_disabled_notice);
        }
    } catch (error) {
    }
}

async function saveDetectionSettings(updates, { silent = false } = {}) {
    try {
        const response = await fetch('/api/settings/detection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            if (data.settings) {
                applyDetectionSettingsToForm(data.settings);
            }
            throw new Error(data.error || 'Failed to save settings');
        }
        applyDetectionSettingsToForm(data.settings);
        if (data.show_auto_exclusion_disabled_toast) {
            showToast(AUTO_EXCLUSION_DISABLED_TOAST);
        } else if (!silent) {
            showToast('Settings saved');
        }
        return data;
    } catch (error) {
        showToast(error.message || 'Failed to save settings');
        return null;
    }
}

function renderSettingsCategoryResults(categories) {
    const results = elements.settingsDefaultCategoryResults;
    if (!results) return;

    results.innerHTML = '';
    (categories || []).forEach((category) => {
        const resultItem = document.createElement('div');
        resultItem.classList.add('search-result-item');
        const categoryName = typeof category === 'string' ? category : category.name;
        resultItem.textContent = categoryName;
        resultItem.addEventListener('click', () => {
            results.innerHTML = '';
            if (elements.settingsDefaultCategory) {
                elements.settingsDefaultCategory.value = categoryName;
            }
            saveDetectionSettings({ default_category: categoryName });
        });
        results.appendChild(resultItem);
    });
}

function handleSettingsCategorySearch() {
    const input = elements.settingsDefaultCategory;
    if (!input) return;

    const query = input.value.trim();
    if (query.length < 2) {
        if (elements.settingsDefaultCategoryResults) {
            elements.settingsDefaultCategoryResults.innerHTML = '';
        }
        return;
    }

    fetch(`/api/categories?query=${encodeURIComponent(query)}`)
        .then((response) => response.json())
        .then((data) => renderSettingsCategoryResults(data))
        .catch(() => {});
}

function scheduleSettingsDefaultCategorySave() {
    clearTimeout(settingsCategorySaveTimer);
    settingsCategorySaveTimer = setTimeout(() => {
        const value = elements.settingsDefaultCategory?.value.trim();
        if (!value) return;
        saveDetectionSettings({ default_category: value }, { silent: true });
    }, 500);
}

function scheduleSettingsSwitchDelaySave() {
    clearTimeout(settingsDelaySaveTimer);
    settingsDelaySaveTimer = setTimeout(() => {
        const rawValue = elements.settingsSwitchDelay?.value;
        const parsed = Number(rawValue);
        if (!Number.isFinite(parsed) || parsed < 0) {
            showToast('Switch delay must be 0 or greater');
            if (elements.settingsSwitchDelay) {
                elements.settingsSwitchDelay.value = appState.detectionSettings.switch_delay_seconds;
            }
            return;
        }
        saveDetectionSettings({ switch_delay_seconds: parsed }, { silent: true });
    }, 400);
}

async function loadWindowSettings() {
    try {
        let minimizeToTray = false;
        let autostartWindows = false;
        if (window.pywebview?.api?.js_get_minimize_to_tray) {
            minimizeToTray = await window.pywebview.api.js_get_minimize_to_tray();
            if (window.pywebview.api.js_get_autostart_with_windows) {
                autostartWindows = await window.pywebview.api.js_get_autostart_with_windows();
            }
        } else {
            const response = await fetch('/api/settings/window');
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const settings = await response.json();
            minimizeToTray = settings.minimize_to_tray === true;
            autostartWindows = settings.autostart_with_windows === true;
        }
        if (elements.settingsMinimizeToTray) {
            elements.settingsMinimizeToTray.checked = minimizeToTray;
        }
        if (elements.settingsAutostartWindows) {
            elements.settingsAutostartWindows.checked = autostartWindows;
        }
    } catch (error) {
    }
}

async function saveMinimizeToTraySetting(enabled, { silent = true } = {}) {
    try {
        if (window.pywebview?.api?.js_set_minimize_to_tray) {
            await window.pywebview.api.js_set_minimize_to_tray(Boolean(enabled));
            if (elements.settingsMinimizeToTray) {
                elements.settingsMinimizeToTray.checked = Boolean(enabled);
            }
            return true;
        }

        const response = await fetch('/api/settings/window', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ minimize_to_tray: Boolean(enabled) }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to save settings');
        }
        if (elements.settingsMinimizeToTray) {
            elements.settingsMinimizeToTray.checked = data.settings?.minimize_to_tray === true;
        }
        if (!silent) {
            showToast('Settings saved');
        }
        return true;
    } catch (error) {
        showToast('Failed to save settings');
        return false;
    }
}

async function saveAutostartWithWindowsSetting(enabled, { silent = true } = {}) {
    try {
        if (window.pywebview?.api?.js_set_autostart_with_windows) {
            const ok = await window.pywebview.api.js_set_autostart_with_windows(Boolean(enabled));
            if (!ok) {
                throw new Error('Failed to update Windows autostart');
            }
            if (elements.settingsAutostartWindows) {
                elements.settingsAutostartWindows.checked = Boolean(enabled);
            }
            return true;
        }

        const response = await fetch('/api/settings/window', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ autostart_with_windows: Boolean(enabled) }),
        });
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Failed to save settings');
        }
        if (elements.settingsAutostartWindows) {
            elements.settingsAutostartWindows.checked = data.settings?.autostart_with_windows === true;
        }
        if (!silent) {
            showToast('Settings saved');
        }
        return true;
    } catch (error) {
        showToast('Failed to save autostart setting');
        return false;
    }
}

function setupDetectionSettings() {
    const categoryInput = elements.settingsDefaultCategory;
    const delayInput = elements.settingsSwitchDelay;
    const autoLockCategory = elements.settingsAutoLockCategory;
    const autoLockTitle = elements.settingsAutoLockTitle;
    const useDiscordDetectable = elements.settingsUseDiscordDetectable;
    const minimizeToTray = elements.settingsMinimizeToTray;
    const autostartWindows = elements.settingsAutostartWindows;
    const themeSelect = elements.settingsTheme;
    const openThemesFolderBtn = elements.settingsOpenThemesFolderBtn;

    if (themeSelect) {
        themeSelect.addEventListener('mousedown', () => {
            refreshThemeOptions();
        });
        themeSelect.addEventListener('focus', () => {
            refreshThemeOptions();
        });
        themeSelect.addEventListener('change', () => {
            saveThemeSelection(themeSelect.value, { silent: true });
        });
    }

    if (openThemesFolderBtn) {
        openThemesFolderBtn.addEventListener('click', openThemesFolder);
    }

    if (categoryInput) {
        categoryInput.addEventListener('input', debounce(handleSettingsCategorySearch, 300));
        categoryInput.addEventListener('blur', scheduleSettingsDefaultCategorySave);
        categoryInput.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && elements.settingsDefaultCategoryResults) {
                elements.settingsDefaultCategoryResults.innerHTML = '';
            }
        });
    }

    if (delayInput) {
        delayInput.addEventListener('input', scheduleSettingsSwitchDelaySave);
        delayInput.addEventListener('change', scheduleSettingsSwitchDelaySave);
    }

    if (autoLockCategory) {
        autoLockCategory.addEventListener('change', () => {
            saveDetectionSettings({
                auto_lock_category_on_manual_update: autoLockCategory.checked,
            }, { silent: true });
        });
    }

    if (autoLockTitle) {
        autoLockTitle.addEventListener('change', () => {
            saveDetectionSettings({
                auto_lock_title_on_manual_update: autoLockTitle.checked,
            }, { silent: true });
        });
    }

    if (useDiscordDetectable) {
        useDiscordDetectable.addEventListener('change', async () => {
            const data = await saveDetectionSettings({
                use_discord_detectable: useDiscordDetectable.checked,
            }, { silent: true });
            if (!data) {
                useDiscordDetectable.checked = !useDiscordDetectable.checked;
                return;
            }
            await fullReloadExcludedAppsLists().catch(() => {});
        });
    }

    if (minimizeToTray) {
        minimizeToTray.addEventListener('change', () => {
            saveMinimizeToTraySetting(minimizeToTray.checked, { silent: true });
        });
    }

    if (autostartWindows) {
        autostartWindows.addEventListener('change', async () => {
            const ok = await saveAutostartWithWindowsSetting(
                autostartWindows.checked,
                { silent: true }
            );
            if (!ok) {
                autostartWindows.checked = !autostartWindows.checked;
            }
        });
    }

    document.addEventListener('click', (e) => {
        const results = elements.settingsDefaultCategoryResults;
        const input = elements.settingsDefaultCategory;
        if (!results || !input || !results.childElementCount) return;
        if (results.contains(e.target) || input.contains(e.target)) return;
        results.innerHTML = '';
    });
}

// Setup tab switching
function setupTabSwitching() {
    
    // Get all tab buttons
    const tabButtons = document.querySelectorAll('.tab-button');
    
    // Add click event listeners to each tab button
    tabButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            const tabId = this.getAttribute('data-tab');
            switchTab(tabId);
        });
    });
}

// Switch tab function
function switchTab(tabId) {
    
    // Update app state
    appState.activeTab = tabId;
    
    // Get all tab buttons and content
    const tabButtons = document.querySelectorAll('.tab-button');
    const tabContents = document.querySelectorAll('.tab-content');
    
    // Remove active class from all buttons and content
    tabButtons.forEach(button => button.classList.remove('active'));
    tabContents.forEach(content => content.classList.remove('active'));
    
    // Add active class to selected tab button and content
    document.querySelector(`.tab-button[data-tab="${tabId}"]`).classList.add('active');
    document.getElementById(tabId).classList.add('active');
    
    // Load data for specific tabs
    if (tabId === 'categories') {
        loadDetectedApps({ useCache: true });
    } else if (tabId === 'games-apps') {
        refreshActiveGamesAppsSubtab();
    } else if (tabId === 'settings') {
        loadDetectionSettings();
        refreshThemeOptions();
    } else if (tabId === 'info') {
        refreshUpdateUiFromState();
    }
}

function refreshActiveGamesAppsSubtab() {
    const subtab = appState.activeSubtab || 'apps';
    if (subtab === 'excluded-apps') {
        loadExcludedApps();
    } else {
        loadApps();
    }
}

// Setup subtab switching
function setupSubtabSwitching() {
    
    // Add click event listeners to each subtab button
    elements.subtabButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            e.preventDefault();
            const subtabId = this.getAttribute('data-subtab');
            switchSubtab(subtabId);
        });
    });
}

// Switch subtab function
function switchSubtab(subtabId) {
    
    // Update app state
    appState.activeSubtab = subtabId;
    
    // Get all subtab buttons and content
    const subtabButtons = document.querySelectorAll('.subtab-button');
    const subtabContents = document.querySelectorAll('.subtab-content');
    
    // Remove active class from all buttons and content
    subtabButtons.forEach(button => button.classList.remove('active'));
    subtabContents.forEach(content => content.classList.remove('active'));
    
    // Add active class to selected subtab button and content
    document.querySelector(`.subtab-button[data-subtab="${subtabId}"]`).classList.add('active');
    document.getElementById(subtabId).classList.add('active');
    
    refreshActiveGamesAppsSubtab();
}

// Setup excluded apps functionality
function setupExcludedApps() {
    
    // Main List Buttons
    elements.addListBtn = document.getElementById('add-list-btn');
    elements.reloadExcludedAppsBtn = document.getElementById('excluded-reload-btn');
    elements.openExcludedFileBtn = document.getElementById('open-excluded-file-btn');
    
    // Add List Modal Options
    elements.createNewOption = document.getElementById('createNewOption');
    elements.addLocalOption = document.getElementById('addLocalOption');
    elements.addFromUrlOption = document.getElementById('addFromUrlOption');
    
    // Modal Elements
    elements.addListModal = document.getElementById('addListModal');
    elements.createNewListModal = document.getElementById('createNewListModal');
    elements.addLocalListModal = document.getElementById('addLocalListModal');
    elements.addFromUrlModal = document.getElementById('addFromUrlModal');
    
    // Create New List Elements
    elements.newListName = document.getElementById('newListName');
    elements.createNewListBtn = document.getElementById('createNewListBtn');
    elements.cancelNewListBtn = document.getElementById('cancelNewListBtn');
    
    // Add Local List Elements
    elements.addLocalListShowFolderBtn = document.getElementById('addLocalListShowFolderBtn');
    elements.addLocalListOkBtn = document.getElementById('addLocalListOkBtn');
    
    // Add From URL Elements
    elements.listUrl = document.getElementById('listUrl');
    elements.listName = document.getElementById('listName');
    elements.addUrlBtn = document.getElementById('addUrlBtn');
    elements.cancelUrlBtn = document.getElementById('cancelUrlBtn');
    
    // Event Listeners
    if (elements.addListBtn) {
        elements.addListBtn.addEventListener('click', () => {
            showModal('addListModal');
        });
    } else {
    }
    
    // Reload button removed - auto-update on changes
    
    const excludedShowFolderBtn = document.getElementById('excluded-show-folder-btn');
    if (excludedShowFolderBtn) {
        excludedShowFolderBtn.addEventListener('click', () => openListFolder('/api/excluded-apps'));
    }

    if (elements.reloadExcludedAppsBtn) {
        elements.reloadExcludedAppsBtn.addEventListener('click', handleReloadExcludedApps);
    }

    if (elements.openExcludedFileBtn) {
        elements.openExcludedFileBtn.addEventListener('click', handleOpenExcludedListFile);
    }

    const excludedListEnabledBtn = document.getElementById('excluded-list-enabled-btn');
    if (excludedListEnabledBtn) {
        excludedListEnabledBtn.addEventListener('click', handleExcludedListEnabledToggle);
    }
    
    // Excluded apps list change event
    if (elements.excludedAppsList) {
        elements.excludedAppsList.addEventListener('change', handleExcludedAppsSelection);
    } else {
    }
    
    // Modal Option Event Listeners
    elements.createNewOption.addEventListener('click', () => {
        hideModal('addListModal');
        showModal('createNewListModal');
    });
    
    elements.addLocalOption.addEventListener('click', () => {
        hideModal('addListModal');
        configureAddLocalListModal();
        showModal('addLocalListModal');
    });
    
    elements.addFromUrlOption.addEventListener('click', () => {
        hideModal('addListModal');
        showModal('addFromUrlModal');
    });
    
    // Button Event Listeners
    elements.createNewListBtn.addEventListener('click', createNewList);
    elements.cancelNewListBtn.addEventListener('click', () => hideModal('createNewListModal'));
    
    elements.addLocalListShowFolderBtn.addEventListener('click', () => {
        openListFolder(getListFolderApiPrefix());
    });
    elements.addLocalListOkBtn.addEventListener('click', () => {
        hideModal('addLocalListModal');
        const isAppsTab = appState.activeTab === 'games-apps' && appState.activeSubtab === 'apps';
        const reloadPromise = isAppsTab
            ? fullReloadDetectedGamesLists()
            : fullReloadExcludedAppsLists();
        reloadPromise.catch(error => {
            showToast('Failed to reload lists');
        });
    });
    
    elements.addUrlBtn.addEventListener('click', addListFromUrl);
    elements.cancelUrlBtn.addEventListener('click', () => hideModal('addFromUrlModal'));
    
    // Excluded apps action buttons
    elements.editBtn.addEventListener('click', handleEditExcludedApp);
    elements.removeBtn.addEventListener('click', handleRemoveExcludedApp);
    
    // Close buttons for modals
    document.querySelectorAll('.close').forEach(closeBtn => {
        closeBtn.addEventListener('click', () => {
            // Find the parent modal
            const modal = closeBtn.closest('.modal');
            if (modal) {
                modal.style.display = 'none';
            }
        });
    });
    
    // Load the excluded apps on startup
    loadExcludedApps();
}

/**
 * Show a modal dialog
 */
function showModal(modalId) {
    const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
    if (!modal) {
        console.error(`Modal not found: ${modalId}`);
        return;
    }
    
    
    if (modalId === 'addListModal') {
        configureAddListModal();
    }

    if (modalId === 'addLocalListModal') {
        configureAddLocalListModal();
    }
    
    modal.style.display = 'flex';
}

function configureAddListModal() {
    const isAppsTab = appState.activeTab === 'games-apps' && appState.activeSubtab === 'apps';
    const title = document.getElementById('addListModalTitle');
    if (title) {
        title.textContent = isAppsTab ? 'Add Detected Games List' : 'Add Excluded App List';
    }
}

function getListFolderApiPrefix() {
    const isAppsTab = appState.activeTab === 'games-apps' && appState.activeSubtab === 'apps';
    return isAppsTab ? '/api/apps' : '/api/excluded-apps';
}

function configureAddLocalListModal() {
    const isAppsTab = appState.activeTab === 'games-apps' && appState.activeSubtab === 'apps';
    const message = document.getElementById('addLocalListMessage');
    if (message) {
        message.textContent = isAppsTab
            ? 'To add a list, place your .txt file in the detected apps folder, then click Reload.'
            : 'To add a list, place your .txt file in the excluded apps folder, then click Reload.';
    }
}

/**
 * Hide a modal dialog
 */
function hideModal(modalId) {
    const modal = typeof modalId === 'string' ? document.getElementById(modalId) : modalId;
    if (!modal) {
        console.error(`Modal not found: ${modalId}`);
        return;
    }
    
    
    modal.style.display = 'none';
}

// Load excluded apps from the backend
// Load excluded apps lists
function getListKey(list) {
    return list.path || list.url || '';
}

function appendListSelectOption(selectEl, list) {
    const option = document.createElement('option');
    option.value = getListKey(list);
    option.textContent = list.name;
    option.dataset.name = list.name;
    option.dataset.source = list.source || 'local';
    if (list.path) {
        option.dataset.path = list.path;
    }
    if (list.url) {
        option.dataset.url = list.url;
    }
    const enabled = list.enabled !== false;
    option.dataset.enabled = enabled ? 'true' : 'false';
    if (!enabled) {
        option.classList.add('list-disabled');
    }
    selectEl.appendChild(option);
    return option;
}

function buildSelectedListFromOption(option) {
    return {
        path: option.dataset.path || '',
        name: option.dataset.name || option.textContent,
        source: option.dataset.source,
        url: option.dataset.url || '',
        enabled: option.dataset.enabled !== 'false'
    };
}

function updateListEnabledButton(button, enabled, hasSelection) {
    if (!button) {
        return;
    }
    button.disabled = !hasSelection;
    button.textContent = hasSelection ? (enabled ? 'Disable' : 'Enable') : 'Disable';
}

function setListEnabledState(apiEndpoint, list, enabled, reloadFn) {
    return fetch(apiEndpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            path: list.path || '',
            url: list.url || '',
            enabled
        })
    })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                return reloadFn(getListKey(list));
            }
            showToast(result.error || 'Failed to update list');
            throw new Error(result.error || 'Failed to update list');
        });
}

function loadExcludedApps(selectedKey = null) {
    
    // Clear the current list
    elements.excludedAppsList.innerHTML = '';
    
    // Disable buttons initially
    elements.editBtn.disabled = true;
    elements.removeBtn.disabled = true;
    if (elements.openExcludedFileBtn) {
        elements.openExcludedFileBtn.disabled = true;
    }
    updateListEnabledButton(document.getElementById('excluded-list-enabled-btn'), true, false);
    
    // Hide source info
    const sourceDiv = document.getElementById('excluded-apps-source');
    if (sourceDiv) {
        sourceDiv.style.display = 'none';
    }
    
    // Make API call to get the list of excluded apps
    fetch('/api/excluded-apps/list')
        .then(response => response.json())
        .then(data => {
            // Store in app state
            appState.excludedApps.lists = data;
            
            // Reset the selected list
            appState.excludedApps.selectedList = null;
            
            // Populate the list
            if (data.length === 0) {
                const option = document.createElement('option');
                option.textContent = 'No lists available';
                option.disabled = true;
                elements.excludedAppsList.appendChild(option);
            } else {
                let selectedIndex = 0;
                data.forEach((list, index) => {
                    appendListSelectOption(elements.excludedAppsList, list);
                    if (selectedKey && getListKey(list) === selectedKey) {
                        selectedIndex = index;
                    }
                });
                elements.excludedAppsList.selectedIndex = selectedIndex;
                handleExcludedAppsSelection();
            }
        })
        .catch(error => {
            showToast('Failed to load excluded apps lists');
        });
}

// Handle excluded apps list selection change
function handleExcludedAppsSelection() {
    const selectedOption = elements.excludedAppsList.options[elements.excludedAppsList.selectedIndex];
    const sourceDiv = document.getElementById('excluded-apps-source');
    
    if (!selectedOption || selectedOption.disabled) {
        // Disable action buttons
        elements.editBtn.disabled = true;
        elements.removeBtn.disabled = true;
        if (elements.openExcludedFileBtn) {
            elements.openExcludedFileBtn.disabled = true;
        }
        updateListEnabledButton(document.getElementById('excluded-list-enabled-btn'), true, false);
        appState.excludedApps.selectedList = null;
        
        // Hide source info
        if (sourceDiv) {
            sourceDiv.style.display = 'none';
        }
        return;
    }
    
    // Store selected list info
    const listInfo = buildSelectedListFromOption(selectedOption);
    
    // Show source info
    if (sourceDiv) {
        if (listInfo.source === 'url') {
            sourceDiv.innerHTML = `<span class="source-info">${icon('globe-alt', 'icon-sm')}<span><strong>Source:</strong> ${listInfo.url}</span></span>`;
        } else {
            sourceDiv.innerHTML = `<span class="source-info">${icon('folder', 'icon-sm')}<span><strong>Location:</strong> ${listInfo.path}</span></span>`;
        }
        sourceDiv.style.display = 'block';
    }
    
    // Update button states based on list type
    
    if (!elements.editBtn) {
        return;
    }
    
    if (listInfo.source === 'url') {
        // URL lists: cannot edit, can remove
        elements.editBtn.disabled = true;
        elements.removeBtn.disabled = false;
        if (elements.openExcludedFileBtn) {
            elements.openExcludedFileBtn.disabled = false;
        }
    } else {
        // Local lists: can edit, can remove
        elements.editBtn.disabled = false;
        elements.removeBtn.disabled = false;
        if (elements.openExcludedFileBtn) {
            elements.openExcludedFileBtn.disabled = false;
        }
    }
    
    appState.excludedApps.selectedList = listInfo;
    updateListEnabledButton(document.getElementById('excluded-list-enabled-btn'), listInfo.enabled, true);
}

function handleExcludedListEnabledToggle() {
    const list = appState.excludedApps.selectedList;
    if (!list) {
        return;
    }

    const enabled = !list.enabled;
    setListEnabledState(
        '/api/excluded-apps/set-enabled',
        list,
        enabled,
        async (selectedKey) => {
            await fullReloadExcludedAppsLists({ selectedKey });
            if (isAutoExcludedAppsList(list) && !enabled) {
                await loadDetectionSettings();
            }
        }
    ).catch(error => {
        showToast('Failed to update list');
    });
}

// Create a new list
function createNewList() {
    const name = elements.newListName.value.trim();
    
    if (!name) {
        showToast('Please enter a valid name');
        return;
    }
    
    // Determine which API to use based on current tab
    const isAppsTab = appState.activeTab === 'games-apps' && appState.activeSubtab === 'apps';
    const apiEndpoint = isAppsTab ? '/api/detected-apps/create' : '/api/excluded-apps/create';
    
    // Send request to create new list
    fetch(apiEndpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ name })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('List created successfully');

            const selectedKey = data.path || null;
            const reloadPromise = isAppsTab
                ? fullReloadDetectedGamesLists(selectedKey)
                : fullReloadExcludedAppsLists({ selectedKey });

            reloadPromise
                .catch(error => {
                    showToast('List created but reload failed');
                })
                .finally(() => {
                    hideModal(elements.createNewListModal);
                    elements.newListName.value = '';
                });
        } else {
            showToast(data.error || 'Failed to create list');
        }
    })
    .catch(error => {
        showToast('Failed to create list');
    });
}

// Add a list from URL
function addListFromUrl() {
    const url = elements.listUrl.value.trim();
    const name = elements.listName.value.trim();
    
    if (!url) {
        showToast('Please enter a valid URL');
        return;
    }
    
    // Determine which API to use based on current tab
    const isAppsTab = appState.activeTab === 'games-apps' && appState.activeSubtab === 'apps';
    const apiEndpoint = isAppsTab ? '/api/detected-apps/add-url' : '/api/excluded-apps/add-url';
    
    // Send request to add URL list (live loading)
    fetch(apiEndpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            url: url,
            name: name || null  // Use null if name is empty
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('URL list added successfully');

            const reloadPromise = isAppsTab
                ? fullReloadDetectedGamesLists()
                : fullReloadExcludedAppsLists();

            reloadPromise
                .catch(error => {
                    showToast('List added but reload failed');
                })
                .finally(() => {
                    hideModal(elements.addFromUrlModal);
                    elements.listUrl.value = '';
                    elements.listName.value = '';
                });
        } else {
            const errorMessage = data.error || 'Failed to add URL list';
            
            // Show a more detailed error message for validation failures
            if (errorMessage.includes('Invalid URL') || errorMessage.includes('HTML') || errorMessage.includes('content type')) {
                showToast(`❌ ${errorMessage}. Please make sure the URL points to a plain text file.`);
            } else {
                showToast(`❌ ${errorMessage}`);
            }
        }
    })
    .catch(error => {
        showToast('Failed to download list');
    });
}

// Handle update list
function handleUpdateList() {
    if (!appState.excludedApps.selectedList) return;
    
    const list = appState.excludedApps.selectedList;
    
    // Confirm update
    elements.modalTitle.textContent = 'Update List';
    elements.modalContent.innerHTML = `
        <p>Are you sure you want to update "${list.name}" from its source URL?</p>
    `;
    
    // Show the modal
    elements.modalOverlay.classList.remove('hidden');
    
    // Set up confirm button handler
    elements.modalConfirm.style.display = 'block';
    elements.modalCancel.textContent = 'Cancel';
    elements.modalConfirm.onclick = confirmUpdateList;
    elements.modalCancel.onclick = closeModal;
    elements.modalClose.onclick = closeModal;
}

// Confirm update list
function confirmUpdateList() {
    const list = appState.excludedApps.selectedList;
    
    // Send API request
    fetch(`/api/excluded-apps/update?path=${encodeURIComponent(list.path)}`)
    .then(response => response.json())
    .then(result => {
        closeModal();
        if (result.success) {
            showToast('List updated successfully');
        } else {
            showToast(`Failed to update list: ${result.error}`);
        }
    })
    .catch(error => {
        closeModal();
        showToast('An error occurred while updating the list');
    });
}

// Handle remove list
function handleRemoveList() {
    if (!appState.excludedApps.selectedList) return;
    
    const list = appState.excludedApps.selectedList;
    const isUrlSource = list.source === 'url';
    
    // Confirm removal
    elements.modalTitle.textContent = 'Remove List';
    
    if (isUrlSource) {
        elements.modalContent.innerHTML = `
            <p>Do you really want to remove "${list.name}"?</p>
        `;
    } else {
        elements.modalContent.innerHTML = `
            <p>How do you want to remove "${list.name}"?</p>
            <div class="radio-group">
                <label>
                    <input type="radio" name="remove-option" value="keep" checked>
                    Remove from list but keep the file
                </label>
                <br>
                <label>
                    <input type="radio" name="remove-option" value="delete">
                    Remove from list and delete the file
                </label>
            </div>
        `;
    }
    
    // Show the modal
    elements.modalOverlay.classList.remove('hidden');
    
    // Set up confirm button handler
    elements.modalConfirm.style.display = 'block';
    elements.modalCancel.textContent = 'Cancel';
    elements.modalConfirm.onclick = confirmRemoveList;
    elements.modalCancel.onclick = closeModal;
    elements.modalClose.onclick = closeModal;
}

// Confirm remove list
function confirmRemoveList() {
    const list = appState.excludedApps.selectedList;
    const isUrlSource = list.source === 'url';
    
    // For URL source, always delete the file
    let deleteFile = isUrlSource;
    
    // For local files, check the selected option
    if (!isUrlSource) {
        const removeOption = document.querySelector('input[name="remove-option"]:checked').value;
        deleteFile = removeOption === 'delete';
    }
    
    // Send API request
    fetch(`/api/excluded-apps/remove?path=${encodeURIComponent(list.path)}&delete=${deleteFile}`)
    .then(response => response.json())
    .then(result => {
        closeModal();
        if (result.success) {
            showToast('List removed successfully');
            fullReloadExcludedAppsLists()
                .then(() => {
                    if (isAutoExcludedAppsList(list)) {
                        return loadDetectionSettings();
                    }
                })
                .catch(error => {
                    showToast('List removed but reload failed');
                });
        } else {
            showToast(`Failed to remove list: ${result.error}`);
        }
    })
    .catch(error => {
        closeModal();
        showToast('An error occurred while removing the list');
    });
}

// Close modal
function closeModal() {
    elements.modalOverlay.classList.add('hidden');
    elements.modalContent.innerHTML = '';
    elements.modalConfirm.onclick = null;
    elements.modalCancel.onclick = null;
    elements.modalClose.onclick = null;
    elements.modalConfirm.style.display = 'block';
    elements.modalCancel.textContent = 'Cancel';
}

function showConfirmationModal(title, message, onConfirm, onCancel = null, confirmText = 'Confirm') {
    elements.modalTitle.textContent = title;
    elements.modalContent.innerHTML = `<p>${message}</p>`;
    elements.modalConfirm.textContent = confirmText;

    elements.modalConfirm.onclick = null;
    elements.modalCancel.onclick = null;
    elements.modalClose.onclick = null;

    const resetConfirmLabel = () => {
        elements.modalConfirm.textContent = 'Confirm';
    };

    elements.modalCancel.onclick = () => {
        closeModal();
        resetConfirmLabel();
        if (onCancel) onCancel();
    };

    elements.modalConfirm.onclick = () => {
        closeModal();
        resetConfirmLabel();
        if (onConfirm) onConfirm();
    };

    elements.modalClose.onclick = () => {
        closeModal();
        resetConfirmLabel();
        if (onCancel) onCancel();
    };

    elements.modalOverlay.classList.remove('hidden');
}

// Handle reload excluded apps
function fullReloadExcludedAppsLists({ shouldNotify = false, toastMessage = 'Excluded apps reloaded successfully', selectedKey = null } = {}) {
    return fetch('/api/excluded-apps/reload')
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                throw new Error(result.error || 'Failed to reload excluded apps');
            }
            if (shouldNotify) {
                showToast(toastMessage);
            }
            loadExcludedApps(selectedKey);
            loadDetectedApps();
            return result;
        });
}

function fullReloadDetectedGamesLists(selectedKey = null, { shouldNotify = false, toastMessage = 'Apps lists reloaded successfully' } = {}) {
    return fetch('/api/apps/reload')
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                throw new Error(result.error || 'Failed to reload apps');
            }
            if (shouldNotify) {
                showToast(toastMessage);
            }
            loadApps(selectedKey);
            loadDetectedApps();
            return result;
        });
}

function handleReloadExcludedApps() {

    fullReloadExcludedAppsLists({ shouldNotify: true })
        .catch(error => {
            showToast('Failed to reload excluded apps');
        });
}

function openListFolder(apiPrefix) {
    fetch(`${apiPrefix}/open-folder`)
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                showToast(result.error || 'Failed to open folder');
            }
        })
        .catch(error => {
            showToast('Failed to open folder');
        });
}

function openListFile(apiPrefix, listPath) {
    if (!listPath) {
        showToast('No file selected');
        return;
    }

    fetch(`${apiPrefix}/open-file?path=${encodeURIComponent(listPath)}`)
        .then(response => response.json())
        .then(result => {
            if (!result.success) {
                showToast(result.error || 'Failed to open file');
            }
        })
        .catch(error => {
            showToast('Failed to open file');
        });
}

function handleOpenExcludedListFile() {
    const list = appState.excludedApps.selectedList;
    if (!list?.path) {
        showToast('No list selected');
        return;
    }
    openListFile('/api/excluded-apps', list.path);
}

function handleOpenAppListFile() {
    const list = appState.apps.selectedList;
    if (!list?.path) {
        showToast('No list selected');
        return;
    }
    openListFile('/api/apps', list.path);
}

function updateAppsOpenFileButton(list) {
    const openAppFileBtn = document.getElementById('open-app-file-btn');
    if (!openAppFileBtn) {
        return;
    }

    if (!list) {
        openAppFileBtn.textContent = 'Open file';
        openAppFileBtn.disabled = true;
        return;
    }

    openAppFileBtn.disabled = false;
    openAppFileBtn.textContent = list.source === 'url' ? 'Edit' : 'Open file';
}

function handleAppsListAction() {
    const list = appState.apps.selectedList;
    if (!list) {
        showToast('No list selected');
        return;
    }

    if (list.source === 'url') {
        showEditUrlListModal();
        return;
    }

    handleOpenAppListFile();
}

function showEditUrlListModal() {
    const list = appState.apps.selectedList;
    if (!list || list.source !== 'url') {
        return;
    }

    const urlInput = document.getElementById('editUrlListUrl');
    const nameInput = document.getElementById('editUrlListName');
    if (!urlInput || !nameInput) {
        return;
    }

    appState.apps.editingUrlList = {
        current_url: list.url,
        stored_name: list.name
    };

    urlInput.value = list.url || '';
    nameInput.value = list.name || '';
    showModal('editUrlListModal');
}

function saveEditUrlList() {
    const editing = appState.apps.editingUrlList;
    if (!editing?.current_url) {
        showToast('No URL list selected for editing');
        return;
    }

    const url = document.getElementById('editUrlListUrl')?.value.trim() || '';
    const name = document.getElementById('editUrlListName')?.value.trim() || '';

    if (!url) {
        showToast('Please enter a valid URL');
        return;
    }

    fetch('/api/detected-apps/edit-url', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            current_url: editing.current_url,
            url,
            name: name || null
        })
    })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                showToast(data.error || 'Failed to update URL list');
                return;
            }

            showToast('URL list updated successfully');
            hideModal('editUrlListModal');
            appState.apps.editingUrlList = null;

            fullReloadDetectedGamesLists(data.url)
                .catch(error => {
                    showToast('List updated but reload failed');
                });
        })
        .catch(error => {
            showToast('Failed to update URL list');
        });
}

// Handle edit excluded app (for local lists)
function handleEditExcludedApp() {
    
    if (!appState.excludedApps.selectedList) {
        showToast('No list selected');
        return;
    }
    
    if (appState.excludedApps.selectedList.source !== 'local') {
        showToast('Only local lists can be edited');
        return;
    }
    
    // Load the list content and open edit modal
    loadListForEditing(appState.excludedApps.selectedList);
}

// Load list content for editing
async function loadListForEditing(listInfo) {
    try {
        
        const response = await fetch(`/api/excluded-apps/get-content?path=${encodeURIComponent(listInfo.path)}`);
        const data = await response.json();
        
        if (data.success) {
            appState.editList = {
                name: listInfo.name,
                path: listInfo.path,
                content: data.content
            };
            openEditModal();
        } else {
            showToast(`Failed to load list: ${data.error}`);
        }
    } catch (error) {
        showToast('Failed to load list for editing');
    }
}

// Open edit modal and populate table
function openEditModal() {
    const modal = document.getElementById('editListModal');
    const listNameSpan = document.getElementById('editListName');
    const tableBody = document.getElementById('editListTableBody');
    const filterInput = document.getElementById('editListFilter');
    
    // Set list name
    listNameSpan.textContent = appState.editList.name;
    
    // Parse content and populate table
    const lines = appState.editList.content.split('\n');
    tableBody.innerHTML = '';
    
    lines.forEach((line, index) => {
        const trimmedLine = line.trim();
        if (trimmedLine && !trimmedLine.startsWith('#')) {
            const parts = splitListFields(trimmedLine, 1);
            const processName = parts[0] ? parts[0].trim() : '';
            const appName = parts[1] ? parts[1].trim() : '';
            
            addTableRow(processName, appName, index);
        }
    });
    
    // Clear filter
    filterInput.value = '';
    
    // Show modal
    showModal(modal);
    
    // Add event listeners
    setupEditModalEventListeners();
}

// Add a row to the edit table
function addTableRow(processName = '', appName = '', originalIndex = null) {
    const tableBody = document.getElementById('editListTableBody');
    const row = document.createElement('tr');
    row.dataset.originalIndex = originalIndex;
    
    row.innerHTML = `
        <td class="select-column">
            <input type="checkbox" class="row-checkbox" onchange="updateRemoveButtonState()">
        </td>
        <td>
            <input type="text" value="${appName}" placeholder="App Title" class="app-name-input">
        </td>
        <td>
            <input type="text" value="${processName}" placeholder="Process Name/Path" class="process-name-input">
        </td>
    `;
    
    tableBody.appendChild(row);
}

// Setup event listeners for edit modal
function setupEditModalEventListeners() {
    const filterInput = document.getElementById('editListFilter');
    const cancelBtn = document.getElementById('cancelEditBtn');
    const modal = document.getElementById('editListModal');
    
    // Filter functionality
    filterInput.addEventListener('input', filterTable);
    
    // Table sorting
    const sortableHeaders = document.querySelectorAll('#editListTable th.sortable');
    sortableHeaders.forEach(header => {
        header.addEventListener('click', () => sortTable(parseInt(header.dataset.column)));
    });
    
    // Cancel button
    cancelBtn.addEventListener('click', () => hideModal(modal));
    
    // Close button
    const closeBtn = modal.querySelector('.modal-close');
    closeBtn.addEventListener('click', () => hideModal(modal));
    
    // Click outside to close
    modal.addEventListener('click', (e) => {
        if (e.target === modal) {
            hideModal(modal);
        }
    });
}

// Filter table rows
function filterTable() {
    const filterValue = document.getElementById('editListFilter').value.toLowerCase();
    const rows = document.querySelectorAll('#editListTableBody tr');
    
    rows.forEach(row => {
        const processName = row.querySelector('.process-name-input').value.toLowerCase();
        const appName = row.querySelector('.app-name-input').value.toLowerCase();
        const matches = processName.includes(filterValue) || appName.includes(filterValue);
        
        row.style.display = matches ? '' : 'none';
    });
}

// Sort table by column
function sortTable(columnIndex) {
    const table = document.getElementById('editListTable');
    const tbody = document.getElementById('editListTableBody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    
    // Determine sort direction
    const currentSort = table.dataset.sortColumn;
    const currentDirection = table.dataset.sortDirection;
    let direction = 'asc';
    
    if (currentSort == columnIndex && currentDirection === 'asc') {
        direction = 'desc';
    }
    
    // Update sort indicators
    document.querySelectorAll('#editListTable th.sortable').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
    });
    
    const header = document.querySelector(`#editListTable th[data-column="${columnIndex}"]`);
    header.classList.add(`sort-${direction}`);
    
    // Store sort state
    table.dataset.sortColumn = columnIndex;
    table.dataset.sortDirection = direction;
    
    // Sort rows
    rows.sort((a, b) => {
        let aValue, bValue;
        
        if (columnIndex === 1) {
            // App Name column
            aValue = a.querySelector('.app-name-input').value.toLowerCase();
            bValue = b.querySelector('.app-name-input').value.toLowerCase();
        } else if (columnIndex === 2) {
            // Process Name column
            aValue = a.querySelector('.process-name-input').value.toLowerCase();
            bValue = b.querySelector('.process-name-input').value.toLowerCase();
        } else {
            // Checkbox column - no sorting
            return 0;
        }
        
        if (direction === 'asc') {
            return aValue.localeCompare(bValue);
        } else {
            return bValue.localeCompare(aValue);
        }
    });
    
    // Re-append sorted rows
    rows.forEach(row => tbody.appendChild(row));
}

// Add new row
function addNewRow() {
    addTableRow('', '', null);
    updateRemoveButtonState();
}

// Remove selected rows
function removeSelectedRows() {
    const selectedRows = document.querySelectorAll('#editListTableBody tr .row-checkbox:checked');
    
    if (selectedRows.length === 0) {
        showToast('No rows selected');
        return;
    }
    
    selectedRows.forEach(checkbox => {
        checkbox.closest('tr').remove();
    });
    
    updateRemoveButtonState();
    showToast(`${selectedRows.length} row(s) removed`);
}

// Update remove button state
function updateRemoveButtonState() {
    const selectedCount = document.querySelectorAll('#editListTableBody tr .row-checkbox:checked').length;
    const removeBtn = document.getElementById('removeSelectedBtn');
    
    removeBtn.disabled = selectedCount === 0;
    removeBtn.textContent = selectedCount > 0 ? `Remove Selected (${selectedCount})` : 'Remove Selected';
}

// Toggle select all
function toggleSelectAll() {
    const selectAllCheckbox = document.getElementById('selectAll');
    const rowCheckboxes = document.querySelectorAll('#editListTableBody tr .row-checkbox');
    
    rowCheckboxes.forEach(checkbox => {
        checkbox.checked = selectAllCheckbox.checked;
    });
    
    updateRemoveButtonState();
}

// Save edited list
async function saveEditedList() {
    try {
        const rows = document.querySelectorAll('#editListTableBody tr');
        const lines = [];
        
        // Check if the original content had a hash name
        const originalContent = appState.editList.content || '';
        const originalLines = originalContent.split('\n');
        const hasHashName = originalLines.length > 0 && originalLines[0].trim().startsWith('#');
        
        // Preserve hash name if it exists
        if (hasHashName) {
            lines.push(originalLines[0]);
        }
        
        rows.forEach(row => {
            const processName = row.querySelector('.process-name-input').value.trim();
            const appName = row.querySelector('.app-name-input').value.trim();
            
            // Skip empty rows
            if (processName || appName) {
                if (appName) {
                    lines.push(joinListFields(processName, appName));
                } else {
                    lines.push(escapeListField(processName));
                }
            }
        });
        
        const content = lines.join('\n');
        
        const response = await fetch('/api/excluded-apps/save-content', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                path: appState.editList.path,
                content: content
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showToast('List saved successfully');
            hideModal(document.getElementById('editListModal'));
            loadExcludedApps(); // Refresh the list
        } else {
            showToast(`Failed to save list: ${data.error}`);
        }
    } catch (error) {
        showToast('Failed to save list');
    }
}

// Handle remove excluded app
function handleRemoveExcludedApp() {
    handleRemoveList();
}

// Setup event listeners for modal buttons
function setupModalButtons() {
    
    // Set up close buttons for all modals
    document.querySelectorAll('.modal-close').forEach(closeBtn => {
        closeBtn.addEventListener('click', function() {
            // Find the parent modal
            const modal = this.closest('.modal');
            if (modal) {
                modal.style.display = 'none';
            }
        });
    });
}

// Setup apps functionality
function setupApps() {
    
    // Main List Buttons
    const addListBtn = document.getElementById('add-app-list-btn');
    const reloadAppsBtn = document.getElementById('apps-reload-btn');
    const removeBtn = document.getElementById('remove-app-btn');
    const openAppFileBtn = document.getElementById('open-app-file-btn');
    const appsShowFolderBtn = document.getElementById('apps-show-folder-btn');
    const appsList = document.getElementById('apps-list');
    
    // Add event listeners
    if (addListBtn) {
        addListBtn.addEventListener('click', handleAddAppList);
    }

    if (appsShowFolderBtn) {
        appsShowFolderBtn.addEventListener('click', () => openListFolder('/api/apps'));
    }

    if (reloadAppsBtn) {
        reloadAppsBtn.addEventListener('click', handleReloadApps);
    }
    
    if (removeBtn) {
        removeBtn.addEventListener('click', handleRemoveApp);
    }

    if (openAppFileBtn) {
        openAppFileBtn.addEventListener('click', handleAppsListAction);
    }

    const saveEditUrlListBtn = document.getElementById('saveEditUrlListBtn');
    const cancelEditUrlListBtn = document.getElementById('cancelEditUrlListBtn');
    if (saveEditUrlListBtn) {
        saveEditUrlListBtn.addEventListener('click', saveEditUrlList);
    }
    if (cancelEditUrlListBtn) {
        cancelEditUrlListBtn.addEventListener('click', () => hideModal('editUrlListModal'));
    }

    const moveUpBtn = document.getElementById('apps-move-up-btn');
    const moveDownBtn = document.getElementById('apps-move-down-btn');
    if (moveUpBtn) {
        moveUpBtn.addEventListener('click', () => handleMoveAppsList('up'));
    }
    if (moveDownBtn) {
        moveDownBtn.addEventListener('click', () => handleMoveAppsList('down'));
    }

    const appsListEnabledBtn = document.getElementById('apps-list-enabled-btn');
    if (appsListEnabledBtn) {
        appsListEnabledBtn.addEventListener('click', handleAppsListEnabledToggle);
    }
    
    if (appsList) {
        appsList.addEventListener('change', handleAppsSelection);
    }
    
    // Load the apps on startup
    loadApps();
}

// Load apps from the backend
function loadApps(selectedKey = null) {
    
    // Clear the current list
    const appsList = document.getElementById('apps-list');
    if (!appsList) return;
    
    appsList.innerHTML = '';
    
    // Disable buttons initially
    const addBtn = document.getElementById('add-app-list-btn');
    const removeBtn = document.getElementById('remove-app-btn');
    if (addBtn) addBtn.disabled = false;
    if (removeBtn) removeBtn.disabled = true;
    updateAppsOpenFileButton(null);
    updateListEnabledButton(document.getElementById('apps-list-enabled-btn'), true, false);
    updateAppsListOrderButtons();
    
    // Hide source info
    const sourceDiv = document.getElementById('apps-source');
    if (sourceDiv) {
        sourceDiv.style.display = 'none';
    }
    
    // Make API call to get the list of apps
    fetch('/api/apps/list')
        .then(response => response.json())
        .then(data => {
            // Store in app state
            appState.apps.lists = data;
            appState.apps.selectedList = null;
            appState.apps.canSaveDetectedGames = data.some(
                list => list.is_default_local && list.enabled !== false
            );
            
            if (data.length === 0) {
                const option = document.createElement('option');
                option.textContent = 'No lists available';
                option.disabled = true;
                appsList.appendChild(option);
            } else {
                let selectedIndex = 0;
                data.forEach((list, index) => {
                    appendListSelectOption(appsList, list);
                    if (selectedKey && getListKey(list) === selectedKey) {
                        selectedIndex = index;
                    }
                });
                appsList.selectedIndex = selectedIndex;
                handleAppsSelection();
            }
        })
        .catch(error => {
            showToast('Failed to load apps lists');
        });
}

// Handle apps list selection change
function handleAppsSelection() {
    const appsList = document.getElementById('apps-list');
    if (!appsList) return;
    
    const selectedOption = appsList.options[appsList.selectedIndex];
    const sourceDiv = document.getElementById('apps-source');
    
    if (!selectedOption || selectedOption.disabled) {
        // Disable action buttons
        const removeBtn = document.getElementById('remove-app-btn');
        if (removeBtn) removeBtn.disabled = true;
        updateAppsOpenFileButton(null);
        updateListEnabledButton(document.getElementById('apps-list-enabled-btn'), true, false);
        updateAppsListOrderButtons();
        
        // Clear source info
        if (sourceDiv) {
            sourceDiv.style.display = 'none';
        }
        
        appState.apps.selectedList = null;
        return;
    }
    
    // Store selected list info
    appState.apps.selectedList = buildSelectedListFromOption(selectedOption);
    
    // Enable action buttons
    const removeBtn = document.getElementById('remove-app-btn');
    if (removeBtn) removeBtn.disabled = false;
    updateAppsOpenFileButton(appState.apps.selectedList);
    updateListEnabledButton(document.getElementById('apps-list-enabled-btn'), appState.apps.selectedList.enabled, true);
    updateAppsListOrderButtons();
    
    // Show source info
    if (sourceDiv) {
        if (selectedOption.dataset.source === 'url') {
            sourceDiv.innerHTML = `<span class="source-info">${icon('globe-alt', 'icon-sm')}<span><strong>Source:</strong> ${selectedOption.dataset.url}</span></span>`;
        } else {
            sourceDiv.innerHTML = `<span class="source-info">${icon('folder', 'icon-sm')}<span><strong>Location:</strong> ${selectedOption.value}</span></span>`;
        }
        sourceDiv.style.display = 'block';
    }
}

function handleAppsListEnabledToggle() {
    const list = appState.apps.selectedList;
    if (!list) {
        return;
    }

    const enabled = !list.enabled;
    setListEnabledState(
        '/api/apps/set-enabled',
        list,
        enabled,
        (selectedKey) => fullReloadDetectedGamesLists(selectedKey)
    ).catch(error => {
        showToast('Failed to update list');
    });
}

function updateAppsListOrderButtons() {
    const appsList = document.getElementById('apps-list');
    const moveUpBtn = document.getElementById('apps-move-up-btn');
    const moveDownBtn = document.getElementById('apps-move-down-btn');
    if (!appsList || !moveUpBtn || !moveDownBtn) return;

    const selectedIndex = appsList.selectedIndex;
    const hasSelection = selectedIndex >= 0
        && appsList.options.length > 0
        && !appsList.options[selectedIndex]?.disabled;

    moveUpBtn.disabled = !hasSelection || selectedIndex === 0;
    moveDownBtn.disabled = !hasSelection || selectedIndex >= appsList.options.length - 1;
}

function handleMoveAppsList(direction) {
    if (!appState.apps.selectedList) {
        showToast('No list selected');
        return;
    }

    const selectedKey = getListKey(appState.apps.selectedList);

    fetch('/api/apps/reorder', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            path: appState.apps.selectedList.path,
            direction
        })
    })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                fullReloadDetectedGamesLists(selectedKey)
                    .catch(error => {
                        showToast('List moved but reload failed');
                    });
            } else {
                showToast(result.error || 'Failed to reorder list');
            }
        })
        .catch(error => {
            showToast('Failed to reorder list');
        });
}

// Handle add app list
function handleAddAppList() {
    showModal('addListModal');
}

// Handle reload apps
function handleReloadApps() {

    fullReloadDetectedGamesLists(null, { shouldNotify: true })
        .catch(error => {
            showToast('Failed to reload apps');
        });
}

// Handle remove app
function handleRemoveApp() {
    
    if (!appState.apps.selectedList) {
        showToast('No list selected');
        return;
    }
    
    const listName = appState.apps.selectedList.name;
    
    // Update the modal message
    const messageElement = document.getElementById('removeAppMessage');
    if (messageElement) {
        messageElement.textContent = `Are you sure you want to remove "${listName}"?`;
    }
    
    // Show the modal
    showModal('removeAppModal');
    
    // Setup the modal event listeners
    setupRemoveAppListModal();
}

// Setup remove app list modal event listeners
function setupRemoveAppListModal() {
    const modal = document.getElementById('removeAppModal');
    const cancelBtn = document.getElementById('cancelRemoveBtn');
    const confirmBtn = document.getElementById('confirmRemoveBtn');
    const closeBtn = modal.querySelector('.modal-close');
    
    if (confirmBtn) {
        confirmBtn.onclick = () => {
            // Make API call to remove the list
            fetch(`/api/apps/remove?path=${encodeURIComponent(appState.apps.selectedList.path)}`)
                .then(response => response.json())
                .then(result => {
                    if (result.success) {
                        fullReloadDetectedGamesLists()
                            .then(() => showToast('List removed successfully'))
                            .catch(error => {
                                showToast('List removed but reload failed');
                            });
                    } else {
                        showToast(`Failed to remove list: ${result.error || 'Unknown error'}`);
                    }
                })
                .catch(error => {
                    showToast('Failed to remove list');
                });
            
            hideModal(modal);
        };
    }
    
    if (cancelBtn) {
        cancelBtn.onclick = () => {
            hideModal(modal);
        };
    }
    
    if (closeBtn) {
        closeBtn.onclick = () => {
            hideModal(modal);
        };
    }
}

// Detected Apps Functions

function detectedAppSortKey(app) {
    return (app.app_name || app.twitch_category || app.process_path || '').toLowerCase();
}

function sortDetectedAppsAlphabetically(apps) {
    return [...(apps || [])].sort((a, b) =>
        detectedAppSortKey(a).localeCompare(detectedAppSortKey(b), undefined, { sensitivity: 'base' })
    );
}

function setDetectedAppsState(apps) {
    appState.detectedApps.apps = sortDetectedAppsAlphabetically(apps);
    updateHomeEditCurrentGameButton();
}

function isUsableBoxArtUrl(url) {
    return Boolean(String(url || '').trim());
}

function setBoxArtImage(img, url) {
    if (!img) {
        return;
    }
    const usable = isUsableBoxArtUrl(url);
    if (usable) {
        img.src = url;
        img.hidden = false;
        img.onerror = () => {
            img.hidden = true;
            img.removeAttribute('src');
        };
    } else {
        img.hidden = true;
        img.removeAttribute('src');
    }
}

function buildBoxArtCoverHtml(url, alt, sizeClass = 'box-art-cover--detected') {
    const usable = isUsableBoxArtUrl(url);
    return `
        <div class="box-art-cover ${sizeClass}">
            <div class="box-art-placeholder" aria-hidden="true"></div>
            ${usable ? `<img class="box-art-image" src="${escapeHtml(url)}" alt="${escapeHtml(alt || '')}" onerror="this.hidden=true;this.removeAttribute('src')">` : ''}
        </div>
    `;
}

function applyBoxArtToCover(cover, url, alt = '') {
    if (!cover) {
        return;
    }
    let img = cover.querySelector('.box-art-image');
    if (!img && isUsableBoxArtUrl(url)) {
        img = document.createElement('img');
        img.className = 'box-art-image';
        cover.appendChild(img);
    }
    if (img) {
        if (alt) {
            img.alt = alt;
        }
        setBoxArtImage(img, url);
    }
}

let detectedAppsBoxArtLoadId = 0;

function applyBoxArtToDetectedAppItem(item, url) {
    const cover = item.querySelector('.box-art-cover');
    const category = item.getAttribute('data-twitch-category') || '';
    applyBoxArtToCover(cover, url, category);
}

async function loadDetectedAppsBoxArtSequentially() {
    const loadId = ++detectedAppsBoxArtLoadId;
    if (!elements.detectedAppsList) {
        return;
    }

    const items = [...elements.detectedAppsList.querySelectorAll('.detected-app-item')];
    const resolvedByCategory = new Map();

    for (const item of items) {
        if (loadId !== detectedAppsBoxArtLoadId) {
            return;
        }

        const category = (item.getAttribute('data-twitch-category') || '').trim();
        if (!category) {
            continue;
        }

        const catKey = category.toLowerCase();
        let url = resolvedByCategory.get(catKey);

        if (!url) {
            const existingImg = item.querySelector('.box-art-cover .box-art-image');
            const existingSrc = existingImg?.getAttribute('src') || '';
            if (isUsableBoxArtUrl(existingSrc)) {
                url = existingSrc;
                resolvedByCategory.set(catKey, url);
            }
        }

        if (!url) {
            try {
                const response = await fetch(`/api/cache/box-art?category=${encodeURIComponent(category)}`);
                if (loadId !== detectedAppsBoxArtLoadId) {
                    return;
                }
                if (!response.ok) {
                    continue;
                }
                const data = await response.json();
                url = data.box_art_url;
                if (isUsableBoxArtUrl(url)) {
                    resolvedByCategory.set(catKey, url);
                } else {
                    url = null;
                }
            } catch (error) {
                continue;
            }
        }

        if (!url) {
            continue;
        }

        applyBoxArtToDetectedAppItem(item, url);
        appState.detectedApps.apps.forEach(app => {
            if ((app.twitch_category || '').trim().toLowerCase() === catKey) {
                app.box_art_url = url;
            }
        });
    }
}

function scheduleDetectedAppsBoxArtLoad() {
    loadDetectedAppsBoxArtSequentially();
}

function normalizeListPath(path) {
    return (path || '').replace(/\\/g, '/').toLowerCase();
}

function pathsReferToSameFile(pathA, pathB) {
    return normalizeListPath(pathA) === normalizeListPath(pathB);
}

function getWritableDetectedLists() {
    if (appState.detectedApps.writableLists?.length) {
        return appState.detectedApps.writableLists;
    }
    return (appState.apps.lists || []).filter(
        list => list.source === 'local' && list.enabled !== false && list.path
    );
}

function buildDetectedAppDetailsSection(app) {
    return `
            <div class="detected-app-path" title="${escapeHtml(app.process_path)}">${escapeHtml(formatPathTail(app.process_path))}</div>
            <div class="detected-app-list">${escapeHtml(app.list_name || 'Unknown List')}</div>
    `;
}

function buildDetectedAppActionsHtml(appId) {
    return `
        <div class="detected-app-actions">
            <button class="btn btn-edit" title="Edit Category" data-action="edit" data-app-id="${appId}">${icon('pencil-square', 'icon-sm')}</button>
            <button class="btn btn-exclude" title="Add to Excluded Apps" data-action="exclude" data-app-id="${appId}">${icon('no-symbol', 'icon-sm')}</button>
            <button class="btn btn-remove" title="Remove from List" data-action="remove" data-app-id="${appId}">${icon('trash', 'icon-sm')}</button>
        </div>
    `;
}

function buildDetectedAppItemInnerHtml(app, appId) {
    const title = app.app_name || '';
    const category = app.twitch_category || '';
    const hasTitle = title && title !== category;
    const boxArtUrl = isUsableBoxArtUrl(app.box_art_url) ? app.box_art_url : '';

    return `
        ${buildBoxArtCoverHtml(boxArtUrl, category, 'box-art-cover--detected')}
        <div class="detected-app-info">
            ${hasTitle ?
                `<div class="detected-app-title">${escapeHtml(title)}</div>
                 <div class="detected-app-category-small">${escapeHtml(category)}</div>` :
                `<div class="detected-app-category">${escapeHtml(category)}</div>`
            }
            ${buildDetectedAppDetailsSection(app)}
        </div>
        ${buildDetectedAppActionsHtml(appId)}
    `;
}

function fetchDetectedAppsPayload() {
    return Promise.all([
        fetch('/api/detected-apps/list').then(response => response.json()),
        fetch('/api/apps/list').then(response => response.json())
    ]).then(([appsData, listsData]) => {
        appState.detectedApps.lists = Array.isArray(listsData) ? listsData : [];
        appState.detectedApps.writableLists = appState.detectedApps.lists.filter(
            list => list.source === 'local' && list.enabled !== false && list.path
        );
        return appsData;
    });
}

function loadDetectedApps({ useCache = false } = {}) {
    console.log('Loading detected apps...');
    
    if (!elements.detectedAppsList) {
        console.error('ERROR: Detected apps list element not found!');
        return;
    }

    if (useCache && appState.detectedApps.apps.length) {
        renderDetectedApps();
        return;
    }
    
    // Clear the current list and state
    elements.detectedAppsList.innerHTML = '';
    appState.detectedApps.apps = [];
    
    // Show loading state
    elements.detectedAppsList.innerHTML = '<div class="detected-app-loading">Loading detected apps...</div>';
    
    // Make API call to get the list of detected apps
    fetchDetectedAppsPayload()
        .then(data => {
            console.log('Detected apps API response:', data);
            if (data.success) {
                setDetectedAppsState(data.apps || []);
                console.log(`Loaded ${appState.detectedApps.apps.length} detected apps:`, appState.detectedApps.apps);
                renderDetectedApps();
            } else {
                console.error(`Failed to load detected apps: ${data.error}`);
                showToast('Failed to load detected apps');
                elements.detectedAppsList.innerHTML = '<div class="detected-app-empty">Failed to load detected apps</div>';
            }
        })
        .catch(error => {
            showToast('Failed to load detected apps');
            elements.detectedAppsList.innerHTML = '<div class="detected-app-empty">Error loading detected apps</div>';
        });
}

function updateSingleDetectedAppById(appId, appName, twitchCategory, boxArtUrl, windowTitle) {
    
    const appItem = document.getElementById(appId);
    if (!appItem) {
        return;
    }
    
    // Get the current process path and list name from the element
    const processPath = appItem.getAttribute('data-process-path');
    const oldWindowTitle = appItem.getAttribute('data-window-title');
    const currentListName = appItem.getAttribute('data-list-name') || 'Local';
    const currentFilePath = appItem.getAttribute('data-file-path') || '';
    
    // Create the updated app data directly from the parameters we already have
    const updatedApp = {
        process_path: processPath,
        app_name: appName || '',
        twitch_category: twitchCategory || '',
        box_art_url: boxArtUrl || '',
        window_title: windowTitle || '',
        list_name: currentListName,
        file_path: currentFilePath
    };
    
    
    // Update the existing element
    updateDetectedAppElement(appItem, updatedApp);
    
    // Update the state
    const stateIndex = appState.detectedApps.apps.findIndex(app => 
        app.process_path === processPath && (app.window_title || '') === (windowTitle || '')
    );
    if (stateIndex !== -1) {
        appState.detectedApps.apps[stateIndex] = updatedApp;
    }
}

function addSingleDetectedApp(processPath, windowTitle, appName, twitchCategory, boxArtUrl, listName = DEFAULT_DETECTED_LOCAL_LIST_NAME, filePath = '') {
    
    // Create the app data directly from the parameters we already have
    const newApp = {
        process_path: processPath,
        app_name: appName || '',
        twitch_category: twitchCategory || '',
        box_art_url: boxArtUrl || '',
        window_title: windowTitle || '',
        list_name: listName,
        file_path: filePath
    };
    
    
    // Add to the state
    appState.detectedApps.apps = sortDetectedAppsAlphabetically([...appState.detectedApps.apps, newApp]);
    
    // Re-render to keep alphabetical order
    renderDetectedApps();
    return;
}

function updateDetectedAppElement(element, appData) {
    
    // Update the data attributes
    element.setAttribute('data-process-path', appData.process_path);
    element.setAttribute('data-window-title', appData.window_title || '');
    element.setAttribute('data-list-name', appData.list_name || 'Unknown List');
    element.setAttribute('data-file-path', appData.file_path || '');
    
    element.innerHTML = buildDetectedAppItemInnerHtml(appData, element.id);
    
    // Re-add event listeners to the action buttons
    const actionButtons = element.querySelectorAll('button[data-action]');
    actionButtons.forEach(button => {
        button.addEventListener('click', handleDetectedAppAction);
    });
    
}

function createDetectedAppElement(appData) {
    const appId = `app-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    const element = document.createElement('div');
    element.className = 'detected-app-item';
    element.id = appId;
    element.setAttribute('data-process-path', appData.process_path);
    element.setAttribute('data-window-title', appData.window_title || '');
    element.setAttribute('data-list-name', appData.list_name || 'Unknown List');
    element.setAttribute('data-file-path', appData.file_path || '');
    
    element.innerHTML = buildDetectedAppItemInnerHtml(appData, appId);
    
    // Add event listeners
    const actionButtons = element.querySelectorAll('button[data-action]');
    actionButtons.forEach(button => {
        button.addEventListener('click', handleDetectedAppAction);
    });
    
    return element;
}

function removeSingleDetectedAppById(appId) {
    
    const element = document.getElementById(appId);
    if (!element) {
        return;
    }
    
    const processPath = element.getAttribute('data-process-path');
    const windowTitle = element.getAttribute('data-window-title');
    
    // Remove from the state
    appState.detectedApps.apps = appState.detectedApps.apps.filter(app => 
        !(app.process_path === processPath && (app.window_title || '') === (windowTitle || ''))
    );
    
    // Remove from the DOM with a smooth animation
    element.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    element.style.opacity = '0';
    element.style.transform = 'translateX(-20px)';
    
    setTimeout(() => {
        element.remove();
    }, 300);
}

function findCategoryElement(processPath, windowTitle) {
    // Find the category element by matching process path and window title
    const appItems = document.querySelectorAll('.detected-app-item');
    for (const item of appItems) {
        const itemProcessPath = item.getAttribute('data-process-path');
        const itemWindowTitle = item.getAttribute('data-window-title') || '';
        
        if (itemProcessPath === processPath && itemWindowTitle === (windowTitle || '')) {
            return item;
        }
    }
    return null;
}

function renderDetectedApps() {
    if (!elements.detectedAppsList) {
        return;
    }
    
    const apps = appState.detectedApps.apps;
    
    if (apps.length === 0) {
        elements.detectedAppsList.innerHTML = '<div class="detected-app-empty">No detected apps yet. Start using applications to see them appear here.</div>';
        populateDetectedAppsListFilter();
        setupDetectedAppsFilter();
        return;
    }
    
    elements.detectedAppsList.innerHTML = apps.map((app, index) => {
        const appId = `app-${Date.now()}-${index}`;

        return `
        <div class="detected-app-item" id="${appId}" data-process-path="${escapeHtml(app.process_path)}" data-window-title="${escapeHtml(app.window_title || '')}" data-twitch-category="${escapeHtml(app.twitch_category || '')}" data-list-name="${escapeHtml(app.list_name || 'Unknown List')}" data-file-path="${escapeHtml(app.file_path || '')}">
            ${buildDetectedAppItemInnerHtml(app, appId)}
        </div>
        `;
    }).join('');
    
    // Add event delegation for the action buttons
    setupDetectedAppEventListeners();
    
    // Setup filter functionality
    populateDetectedAppsListFilter();
    setupDetectedAppsFilter();
    filterDetectedApps();
    
    // Setup add category button
    setupAddCategoryButton();

    scheduleDetectedAppsBoxArtLoad();
}

function setupDetectedAppEventListeners() {
    // Remove existing event listeners to avoid duplicates
    if (elements.detectedAppsList) {
        elements.detectedAppsList.removeEventListener('click', handleDetectedAppAction);
        elements.detectedAppsList.addEventListener('click', handleDetectedAppAction);
    }
}

function populateAddAppListSelect() {
    const select = document.getElementById('add-app-list');
    const readonly = document.getElementById('add-app-list-readonly');
    if (!select || !readonly) {
        return;
    }

    const lists = getWritableDetectedLists();
    if (lists.length > 0) {
        select.classList.remove('hidden');
        readonly.classList.add('hidden');
        const defaultList = lists.find(list => /local/i.test(list.name || '')) || lists[0];
        select.innerHTML = lists.map(list => {
            const selected = pathsReferToSameFile(list.path, defaultList.path) ? ' selected' : '';
            return `<option value="${escapeHtml(list.path)}"${selected}>${escapeHtml(list.name)}</option>`;
        }).join('');
    } else {
        select.classList.add('hidden');
        readonly.classList.remove('hidden');
        readonly.textContent = 'No writable lists available';
    }
}

function getSelectedAddAppListPath() {
    const select = document.getElementById('add-app-list');
    if (select && !select.classList.contains('hidden')) {
        return select.value;
    }
    return '';
}

function getSelectedAddAppListName() {
    const selectedPath = getSelectedAddAppListPath();
    const lists = getWritableDetectedLists();
    const match = lists.find(list => pathsReferToSameFile(list.path, selectedPath));
    return match?.name || DEFAULT_DETECTED_LOCAL_LIST_NAME;
}

function populateEditAppListSelect(app) {
    const select = document.getElementById('edit-app-list');
    const readonly = document.getElementById('edit-app-list-readonly');
    if (!select || !readonly) {
        return;
    }

    const lists = getWritableDetectedLists();
    const canMove = Boolean(
        app.file_path
        && lists.length > 0
        && lists.some(list => pathsReferToSameFile(list.path, app.file_path))
    );

    if (canMove) {
        select.classList.remove('hidden');
        readonly.classList.add('hidden');
        select.innerHTML = lists.map(list => {
            const selected = pathsReferToSameFile(list.path, app.file_path) ? ' selected' : '';
            return `<option value="${escapeHtml(list.path)}"${selected}>${escapeHtml(list.name)}</option>`;
        }).join('');
    } else {
        select.classList.add('hidden');
        readonly.classList.remove('hidden');
        readonly.textContent = app.list_name || 'Unknown List';
    }
}

function getSelectedEditAppListPath() {
    const select = document.getElementById('edit-app-list');
    if (select && !select.classList.contains('hidden')) {
        return select.value;
    }
    return appState.editingApp?.file_path || '';
}

function moveDetectedAppIfNeeded(editingApp) {
    const targetPath = getSelectedEditAppListPath();
    const sourcePath = editingApp.file_path || '';

    if (pathsReferToSameFile(targetPath, sourcePath)) {
        return Promise.resolve({
            success: true,
            file_path: sourcePath,
            list_name: editingApp.list_name
        });
    }

    return fetch('/api/detected-apps/move-list', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            process_path: editingApp.process_path,
            app_name: editingApp.app_name || '',
            twitch_category: editingApp.twitch_category || '',
            window_title: editingApp.window_title || '',
            source_file_path: sourcePath,
            target_file_path: targetPath
        })
    }).then(response => response.json());
}

function submitDetectedAppEdit(processPath, appName, twitchCategory, boxArtUrl, windowTitle) {
    const editingApp = appState.editingApp;
    if (!editingApp) {
        showToast('No app selected for editing');
        return Promise.reject(new Error('No editing app'));
    }

    return moveDetectedAppIfNeeded(editingApp)
        .then(moveResult => {
            if (!moveResult.success) {
                throw new Error(moveResult.error || 'Failed to move app to selected list');
            }

            const targetFilePath = moveResult.file_path || getSelectedEditAppListPath();
            const editData = {
                old_process_path: editingApp.process_path,
                old_app_name: editingApp.app_name || '',
                old_twitch_category: editingApp.twitch_category || '',
                old_window_title: editingApp.window_title || '',
                process_path: processPath,
                app_name: appName,
                twitch_category: twitchCategory,
                window_title: windowTitle || '',
                file_path: targetFilePath
            };

            return fetch('/api/detected-apps/edit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(editData)
            })
                .then(response => response.json())
                .then(data => ({ data, moveResult }));
        });
}

function populateDetectedAppsListFilter() {
    const select = document.getElementById('detectedAppsListFilter');
    if (!select) {
        return;
    }

    const previousValue = select.value;
    const lists = (appState.detectedApps.lists || []).filter(list => list.enabled !== false);
    const listNames = lists.map(list => list.name).filter(Boolean);

    select.innerHTML = '<option value="">Show all</option>' + lists.map(list => {
        return `<option value="${escapeHtml(list.name)}">${escapeHtml(list.name)}</option>`;
    }).join('');

    if (previousValue && listNames.includes(previousValue)) {
        select.value = previousValue;
    } else {
        select.value = '';
    }
}

function setupDetectedAppsFilter() {
    const filterInput = document.getElementById('detectedAppsFilter');
    const listFilter = document.getElementById('detectedAppsListFilter');
    if (!filterInput) return;
    
    // Remove existing event listener to avoid duplicates
    filterInput.removeEventListener('input', filterDetectedApps);
    filterInput.addEventListener('input', filterDetectedApps);

    if (listFilter) {
        listFilter.removeEventListener('change', filterDetectedApps);
        listFilter.addEventListener('change', filterDetectedApps);
    }
}

function filterDetectedApps() {
    const filterValue = document.getElementById('detectedAppsFilter')?.value || '';
    const listFilterValue = document.getElementById('detectedAppsListFilter')?.value || '';
    const appItems = document.querySelectorAll('.detected-app-item');
    
    appItems.forEach(item => {
        const categoryElement = item.querySelector('.detected-app-category');
        const titleElement = item.querySelector('.detected-app-title');
        const categorySmallElement = item.querySelector('.detected-app-category-small');
        const pathElement = item.querySelector('.detected-app-path');
        
        const category = categoryElement ? categoryElement.textContent : '';
        const title = titleElement ? titleElement.textContent : '';
        const categorySmall = categorySmallElement ? categorySmallElement.textContent : '';
        const path = pathElement
            ? (pathElement.getAttribute('title') || pathElement.textContent)
            : '';
        const listName = item.getAttribute('data-list-name') || '';

        const searchableText = [title, category, categorySmall, path, listName].join(' ');
        const matchesText = matchesSearchFilter(searchableText, filterValue);
        const matchesList = !listFilterValue || listName === listFilterValue;
        
        item.style.display = (matchesText && matchesList) ? '' : 'none';
    });
}

function setupAddCategoryButton() {
    const addBtn = document.getElementById('addCategoryBtn');
    if (!addBtn) return;
    
    addBtn.addEventListener('click', () => {
        showAddCategoryModal();
    });
}

let detectedAppsBackToTopInitialized = false;

function setupDetectedAppsBackToTop() {
    if (detectedAppsBackToTopInitialized) {
        return;
    }

    const scrollContainer = document.getElementById('categories');
    const backToTopBtn = document.getElementById('detectedAppsBackToTop');
    if (!scrollContainer || !backToTopBtn) {
        return;
    }

    detectedAppsBackToTopInitialized = true;

    scrollContainer.addEventListener('scroll', updateDetectedAppsBackToTopVisibility);
    backToTopBtn.addEventListener('click', () => {
        scrollContainer.scrollTo({ top: 0, behavior: 'smooth' });
    });

    updateDetectedAppsBackToTopVisibility();
}

function updateDetectedAppsBackToTopVisibility() {
    const scrollContainer = document.getElementById('categories');
    const backToTopBtn = document.getElementById('detectedAppsBackToTop');
    if (!scrollContainer || !backToTopBtn) {
        return;
    }

    backToTopBtn.classList.toggle('visible', scrollContainer.scrollTop > 100);
}

function hideAddCategorySearch() {
    const addResults = document.getElementById('add-category-results');
    if (addResults) {
        addResults.innerHTML = '';
        addResults.dataset.keyboardNav = 'false';
    }
    debouncedAddCategorySearch.cancel();
}

const gameDialogPathMode = {
    add: 'process',
    edit: 'location',
};

function setGameDialogPathMode(dialog, mode) {
    const isAdd = dialog === 'add';
    const processGroup = document.getElementById(isAdd ? 'add-process-select-group' : 'edit-process-select-group');
    const locationGroup = document.getElementById(isAdd ? 'add-location-group' : 'edit-location-group');
    if (!processGroup || !locationGroup) {
        return;
    }

    gameDialogPathMode[dialog] = mode === 'location' ? 'location' : 'process';
    const useProcess = gameDialogPathMode[dialog] === 'process';

    processGroup.classList.toggle('hidden', !useProcess);
    locationGroup.classList.toggle('hidden', useProcess);

    if (useProcess) {
        const select = document.getElementById(isAdd ? 'addCategoryProcess' : 'editCategoryProcess');
        const locationInput = document.getElementById(isAdd ? 'addCategoryLocation' : 'edit-app-location');
        const selectedPath = (locationInput?.value || '').trim();
        loadForegroundProcessSelect(select, { selectedPath });
    }
}

function formatForegroundProcessOptionLabel(process) {
    const windowTitle = (process.window_title || '').trim();
    const processName = (process.process_name || '').trim();
    const pathTail = formatPathTail(process.process_path || '', 36);
    const titlePart = windowTitle || processName || pathTail;
    const pathPart = pathTail || processName;
    if (titlePart && pathPart && titlePart.toLowerCase() !== pathPart.toLowerCase()) {
        return `${titlePart} — ${pathPart}`;
    }
    return titlePart || pathPart || 'Unknown process';
}

function loadForegroundProcessSelect(selectElement, { selectedPath = '' } = {}) {
    if (!selectElement) {
        return Promise.resolve([]);
    }

    selectElement.innerHTML = '<option value="">Loading processes...</option>';
    selectElement.disabled = true;

    return fetch('/api/processes/foreground-apps')
        .then((response) => response.json())
        .then((data) => {
            const processes = Array.isArray(data?.processes) ? data.processes : [];
            selectElement.innerHTML = '';

            if (!processes.length) {
                const emptyOption = document.createElement('option');
                emptyOption.value = '';
                emptyOption.textContent = 'No foreground apps found';
                selectElement.appendChild(emptyOption);
                selectElement.disabled = true;
                return processes;
            }

            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = 'Select a process...';
            selectElement.appendChild(placeholder);

            let matched = false;
            processes.forEach((process) => {
                const option = document.createElement('option');
                option.value = process.process_path || '';
                option.textContent = formatForegroundProcessOptionLabel(process);
                option.title = process.process_path || '';
                if (process.is_foreground) {
                    option.textContent += ' (active)';
                }
                if (
                    selectedPath
                    && process.process_path
                    && process.process_path.toLowerCase() === selectedPath.toLowerCase()
                ) {
                    option.selected = true;
                    matched = true;
                }
                selectElement.appendChild(option);
            });

            if (!matched) {
                placeholder.selected = true;
            }

            selectElement.disabled = false;
            return processes;
        })
        .catch((error) => {
            console.error('Error loading foreground processes:', error);
            selectElement.innerHTML = '';
            const errorOption = document.createElement('option');
            errorOption.value = '';
            errorOption.textContent = 'Failed to load processes';
            selectElement.appendChild(errorOption);
            selectElement.disabled = true;
            return [];
        });
}

function getGameDialogPath(dialog) {
    const mode = gameDialogPathMode[dialog] || 'location';
    if (mode === 'process') {
        const select = document.getElementById(dialog === 'add' ? 'addCategoryProcess' : 'editCategoryProcess');
        return (select?.value || '').trim();
    }

    const locationInput = document.getElementById(dialog === 'add' ? 'addCategoryLocation' : 'edit-app-location');
    return (locationInput?.value || '').trim();
}

function setupGameDialogPathModeToggles(dialog) {
    const isAdd = dialog === 'add';
    const usePathBtn = document.getElementById(isAdd ? 'addUsePathInsteadBtn' : 'editUsePathInsteadBtn');
    const useProcessBtn = document.getElementById(isAdd ? 'addUseProcessInsteadBtn' : 'editUseProcessInsteadBtn');

    if (usePathBtn) {
        usePathBtn.onclick = () => {
            const select = document.getElementById(isAdd ? 'addCategoryProcess' : 'editCategoryProcess');
            const locationInput = document.getElementById(isAdd ? 'addCategoryLocation' : 'edit-app-location');
            if (locationInput && select?.value && !locationInput.value.trim()) {
                locationInput.value = select.value;
            }
            setGameDialogPathMode(dialog, 'location');
        };
    }

    if (useProcessBtn) {
        useProcessBtn.onclick = () => setGameDialogPathMode(dialog, 'process');
    }
}

function closeAddCategoryModal() {
    const modal = document.getElementById('addCategoryModal');
    hideAddCategorySearch();
    document.removeEventListener('mousedown', handleAddCategoryModalOutsideClick);
    if (modal) {
        modal.style.display = 'none';
    }
}

function handleAddCategoryNameSearch() {
    const categoryInput = document.getElementById('addCategoryName');
    const query = categoryInput?.value.trim() || '';

    if (query.length > 2) {
        searchCategoriesForAdd(query);
    } else {
        hideAddCategorySearch();
    }
}

const debouncedAddCategorySearch = debounce(handleAddCategoryNameSearch, 300);

function handleAddCategoryModalOutsideClick(e) {
    const modal = document.getElementById('addCategoryModal');
    if (!modal || modal.style.display !== 'flex') {
        return;
    }

    const searchContainer = document.getElementById('addCategoryName')?.closest('.search-container');
    if (searchContainer && !searchContainer.contains(e.target)) {
        hideAddCategorySearch();
    }
}

function handleAddCategoryNameKeydown(e) {
    const categoryInput = document.getElementById('addCategoryName');
    const addResults = document.getElementById('add-category-results');

    if (e.key === 'Enter') {
        e.preventDefault();
        const query = categoryInput?.value.trim() || '';
        const selectedItem = addResults?.querySelector('.search-result-item.selected');

        if (selectedItem) {
            categoryInput.value = selectedItem.textContent.trim();
            hideAddCategorySearch();
        } else if (query) {
            addCategoryManually();
        }
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        navigateAddCategoryDropdown('down');
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        navigateAddCategoryDropdown('up');
    } else if (e.key === 'Escape') {
        hideAddCategorySearch();
    }
}

function showAddCategoryModal() {
    const modal = document.getElementById('addCategoryModal');
    if (!modal) return;

    const populateAndShow = () => {
        document.getElementById('addCategoryTitle').value = '';
        document.getElementById('addCategoryName').value = '';
        document.getElementById('addCategoryLocation').value = '';
        populateWindowTitleInputs('add-window-title-list', '');
        hideAddCategorySearch();
        populateAddAppListSelect();
        setGameDialogPathMode('add', 'process');
        setupGameDialogPathModeToggles('add');
        modal.style.display = 'flex';
        setupAddCategoryModalEventListeners();
    };

    if (!appState.detectedApps.writableLists?.length) {
        fetch('/api/apps/list')
            .then(response => response.json())
            .then(listsData => {
                appState.detectedApps.writableLists = Array.isArray(listsData)
                    ? listsData.filter(list => list.source === 'local' && list.enabled !== false && list.path)
                    : [];
                populateAndShow();
            })
            .catch(() => populateAndShow());
    } else {
        populateAndShow();
    }
}

function setupAddCategoryModalEventListeners() {
    const modal = document.getElementById('addCategoryModal');
    const categoryInput = document.getElementById('addCategoryName');
    const browseBtn = document.getElementById('browseLocationBtn');
    const cancelBtn = document.getElementById('cancelAddCategoryBtn');
    const saveBtn = document.getElementById('saveAddCategoryBtn');
    const closeBtn = modal?.querySelector('.modal-close');
    const addResults = document.getElementById('add-category-results');

    if (!modal || !categoryInput) {
        return;
    }

    categoryInput.removeEventListener('input', debouncedAddCategorySearch);
    categoryInput.removeEventListener('keydown', handleAddCategoryNameKeydown);
    categoryInput.addEventListener('input', debouncedAddCategorySearch);
    categoryInput.addEventListener('keydown', handleAddCategoryNameKeydown);

    document.removeEventListener('mousedown', handleAddCategoryModalOutsideClick);
    document.addEventListener('mousedown', handleAddCategoryModalOutsideClick);

    setupWindowTitleAddButton('add-window-title-add', 'add-window-title-list');

    if (addResults) {
        addResults.onmouseenter = () => {
            addResults.dataset.keyboardNav = 'false';
            addResults.querySelectorAll('.search-result-item').forEach(item => {
                item.classList.remove('selected');
            });
        };
    }
    
    // Add Enter key handling to all other input fields in the modal
    const allInputs = modal.querySelectorAll('input[type="text"], input[type="file"]');
    allInputs.forEach(input => {
        if (input !== categoryInput) {
            input.onkeydown = (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    addCategoryManually();
                }
            };
        }
    });
    
    if (browseBtn) {
        browseBtn.onclick = () => {
            const existingInput = document.getElementById('temp-file-input-add');
            if (existingInput) {
                document.body.removeChild(existingInput);
            }
            
            const fileInput = document.createElement('input');
            fileInput.id = 'temp-file-input-add';
            fileInput.type = 'file';
            fileInput.accept = '.exe';
            fileInput.style.display = 'none';
            
            fileInput.onchange = (event) => {
                const file = event.target.files[0];
                if (file) {
                    document.getElementById('addCategoryLocation').value = file.path || file.name;
                }
                if (document.body.contains(fileInput)) {
                    document.body.removeChild(fileInput);
                }
            };
            
            fileInput.oncancel = () => {
                setTimeout(() => {
                    if (document.body.contains(fileInput)) {
                        document.body.removeChild(fileInput);
                    }
                }, 100);
            };
            
            document.body.appendChild(fileInput);
            fileInput.click();
        };
    }
    
    if (cancelBtn) {
        cancelBtn.onclick = closeAddCategoryModal;
    }
    
    if (saveBtn) {
        saveBtn.onclick = addCategoryManually;
    }
    
    if (closeBtn) {
        closeBtn.onclick = closeAddCategoryModal;
    }
    
    modal.onclick = (e) => {
        if (e.target === modal) {
            closeAddCategoryModal();
        }
    };
}

function searchCategoriesForAdd(query) {
    fetch(`/api/categories?query=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(data => {
            if (data && data.length > 0) {
                renderAddCategoryResults(data);
            } else {
                hideAddCategorySearch();
            }
        })
        .catch(error => {
            console.error('Error searching categories:', error);
            hideAddCategorySearch();
        });
}

function renderAddCategoryResults(categories) {
    const resultsContainer = document.getElementById('add-category-results');
    if (!resultsContainer) {
        return;
    }

    resultsContainer.innerHTML = '';

    categories.forEach(category => {
        const categoryName = typeof category === 'string' ? category : category.name;
        const resultItem = document.createElement('div');
        resultItem.classList.add('search-result-item');
        resultItem.textContent = categoryName;
        resultItem.addEventListener('mousedown', (e) => {
            e.preventDefault();
        });
        resultItem.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            selectAddCategory(categoryName);
        });
        resultsContainer.appendChild(resultItem);
    });

    positionCategoryDropdown('addCategoryName', 'add-category-results');
}

function selectAddCategory(categoryName) {
    const categoryInput = document.getElementById('addCategoryName');
    if (categoryInput) {
        categoryInput.value = categoryName;
    }
    hideAddCategorySearch();
}

function addCategoryManually() {
    const title = document.getElementById('addCategoryTitle').value.trim();
    const category = document.getElementById('addCategoryName').value.trim();
    const location = getGameDialogPath('add');
    const windowTitle = collectWindowTitles('add-window-title-list');
    
    if (!category || !location) {
        const missing = !category ? 'category' : 'process or location';
        showToast(`Please fill in ${missing}`);
        return;
    }
    
    // Check if this is a manually entered category (not selected from dropdown)
    const isManuallyEntered = !document.querySelector('.search-result-item.selected');
    
    if (isManuallyEntered) {
        // Validate the category exists on Twitch
        validateAndAddCategory(title, category, location, windowTitle);
    } else {
        // Category was selected from dropdown, proceed directly
        addCategoryDirectly(title, category, location, windowTitle);
    }
}

function validateAndAddCategory(title, category, location, windowTitle) {
    
    // Show loading state
    const saveBtn = document.getElementById('saveAddCategoryBtn');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Validating...';
    saveBtn.disabled = true;
    
    fetch(`/api/categories?query=${encodeURIComponent(category)}`)
        .then(response => response.json())
        .then(data => {
            if (data && data.length > 0) {
                // Check for exact match (case insensitive)
                const exactMatch = data.find(cat => 
                    cat.name && cat.name.toLowerCase() === category.toLowerCase()
                );
                
                if (exactMatch) {
                    // Use the exact match from Twitch (with correct casing)
                    addCategoryDirectly(title, exactMatch.name, location, windowTitle);
                } else {
                    showToast('Please enter a valid Twitch category or select one from the dropdown');
                    saveBtn.textContent = originalText;
                    saveBtn.disabled = false;
                    // Don't close modal - let user fix the input
                }
            } else {
                showToast('Please enter a valid Twitch category or select one from the dropdown');
                saveBtn.textContent = originalText;
                saveBtn.disabled = false;
                // Don't close modal - let user fix the input
            }
        })
        .catch(error => {
            showToast('Failed to validate category. Please try again.');
            saveBtn.textContent = originalText;
            saveBtn.disabled = false;
            // Don't close modal - let user try again
        });
}

function validateAndUpdateCategory(processPath, appName, twitchCategory, boxArtUrl, windowTitle) {
    
    // Show loading state
    const saveBtn = document.getElementById('saveCategoryBtn');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Validating...';
    saveBtn.disabled = true;
    
    fetch(`/api/categories?query=${encodeURIComponent(twitchCategory)}`)
        .then(response => response.json())
        .then(data => {
            if (data && data.length > 0) {
                // Check for exact match (case insensitive)
                const exactMatch = data.find(cat => 
                    cat.name && cat.name.toLowerCase() === twitchCategory.toLowerCase()
                );
                
                if (exactMatch) {
                    // Use the exact match from Twitch (with correct casing) and proceed with edit
                    updateDetectedAppDirectly(processPath, appName, exactMatch.name, boxArtUrl, windowTitle);
                } else {
                    showToast('Please enter a valid Twitch category or select one from the dropdown');
                    saveBtn.textContent = originalText;
                    saveBtn.disabled = false;
                    // Don't close modal - let user fix the input
                }
            } else {
                showToast('Please enter a valid Twitch category or select one from the dropdown');
                saveBtn.textContent = originalText;
                saveBtn.disabled = false;
                // Don't close modal - let user fix the input
            }
        })
        .catch(error => {
            showToast('Failed to validate category. Please try again.');
            saveBtn.textContent = originalText;
            saveBtn.disabled = false;
            // Don't close modal - let user try again
        });
}

function completeDetectedAppEdit(processPath, appName, twitchCategory, boxArtUrl, windowTitle, moveResult) {
    const oldCategory = appState.editingApp?.twitch_category || '';
    const editingAppId = appState.editingAppId;
    const oldProcessPath = appState.editingApp?.process_path || '';
    const oldWindowTitle = appState.editingApp?.window_title || '';

    const app = appState.detectedApps.apps.find(a =>
        a.process_path === oldProcessPath && (a.window_title || '') === oldWindowTitle
    );
    if (app) {
        app.process_path = processPath;
        app.app_name = appName;
        app.twitch_category = twitchCategory;
        app.window_title = windowTitle || '';
        if (moveResult?.file_path) {
            app.file_path = moveResult.file_path;
        }
        if (moveResult?.list_name) {
            app.list_name = moveResult.list_name;
        }
    }

    appState.editingApp = null;
    closeEditCategoryModal();
    showToast('App updated successfully');

    const refreshUi = (finalBoxArt) => {
        const appItem = document.getElementById(editingAppId);
        if (appItem) {
            appItem.setAttribute('data-process-path', processPath);
            appItem.setAttribute('data-window-title', windowTitle || '');
            if (moveResult?.list_name) {
                appItem.setAttribute('data-list-name', moveResult.list_name);
            }
            if (moveResult?.file_path) {
                appItem.setAttribute('data-file-path', moveResult.file_path);
            }
        }
        updateSingleDetectedAppById(editingAppId, appName, twitchCategory, finalBoxArt, windowTitle);
    };

    if (twitchCategory !== oldCategory) {
        fetch(`/api/categories?query=${encodeURIComponent(twitchCategory)}`)
            .then(response => response.json())
            .then(categoryData => {
                if (categoryData && categoryData.length > 0) {
                    let bestMatch = categoryData.find(cat =>
                        cat.name && cat.name.toLowerCase() === twitchCategory.toLowerCase()
                    ) || categoryData[0];
                    refreshUi(bestMatch.box_art_url || boxArtUrl);
                } else {
                    refreshUi(boxArtUrl);
                }
            })
            .catch(() => refreshUi(boxArtUrl));
    } else {
        refreshUi(boxArtUrl);
    }
}

function updateDetectedAppDirectly(processPath, appName, twitchCategory, boxArtUrl, windowTitle) {
    submitDetectedAppEdit(processPath, appName, twitchCategory, boxArtUrl, windowTitle)
        .then(({ data, moveResult }) => {
            if (data.status === 'success') {
                completeDetectedAppEdit(processPath, appName, twitchCategory, boxArtUrl, windowTitle, moveResult);
            } else {
                showToast(`Failed to update app: ${data.error || data.message || 'Unknown error'}`);
            }
        })
        .catch(error => {
            showToast(error.message || 'Failed to update app');
        })
        .finally(() => {
            const saveBtn = document.getElementById('saveCategoryBtn');
            if (saveBtn) {
                saveBtn.textContent = 'Save';
                saveBtn.disabled = false;
            }
        });
}

function addCategoryDirectly(title, category, location, windowTitle) {
    // Show loading state
    const saveBtn = document.getElementById('saveAddCategoryBtn');
    const originalText = saveBtn.textContent;
    saveBtn.textContent = 'Adding...';
    saveBtn.disabled = true;
    
    fetch('/api/detected-apps/add-manual', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            title: title,
            category: category,
            location: location,
            window_title: windowTitle,
            file_path: getSelectedAddAppListPath()
        })
    })
    .then(response => response.json())
    .then(data => {
        console.log('Add category response:', data);
        if (data.status === 'success') {
            showToast('Category added successfully');
            closeAddCategoryModal();
            // Add the new category dynamically
            console.log('Adding new category...');
            addSingleDetectedApp(
                location,
                windowTitle,
                title,
                category,
                '',
                getSelectedAddAppListName(),
                getSelectedAddAppListPath()
            );
        } else {
            showToast(data.error || 'Failed to add category');
        }
    })
    .catch(error => {
        console.error('Error adding category:', error);
        showToast('Failed to add category');
    })
    .finally(() => {
        saveBtn.textContent = originalText;
        saveBtn.disabled = false;
    });
}

function handleDetectedAppAction(event) {
    const button = event.target.closest('button[data-action]');
    if (button) {
        const action = button.getAttribute('data-action');
        const appId = button.getAttribute('data-app-id');
        const appItem = document.getElementById(appId);

        if (!appId || !appItem) return;

        const processPath = appItem.getAttribute('data-process-path');
        if (!processPath) return;

        appState.currentAppId = appId;

        switch (action) {
            case 'edit':
                editDetectedAppById(appId);
                break;
            case 'exclude':
                addDetectedAppToExcludedById(appId);
                break;
            case 'remove':
                removeDetectedAppById(appId);
                break;
        }
        return;
    }

    const appItem = event.target.closest('.detected-app-item');
    if (appItem && appItem.id) {
        editDetectedAppById(appItem.id);
    }
}

function editDetectedAppById(appId) {
    
    const appItem = document.getElementById(appId);
    if (!appItem) {
        showToast('App not found');
        return;
    }
    
    // Get app data from the DOM element
    const processPath = appItem.getAttribute('data-process-path');
    const windowTitle = appItem.getAttribute('data-window-title');
    
    // Find the app in the state
    const app = appState.detectedApps.apps.find(a => 
        a.process_path === processPath && (a.window_title || '') === (windowTitle || '')
    );
    
    if (!app) {
        showToast('App not found in current state');
        return;
    }
    
    
    // Store the app data for editing
    appState.editingApp = app;
    appState.editingAppId = appId; // Store the ID for later reference
    
    // Show edit dialog
    showEditDialog(app);
}

function editDetectedApp(processPath, windowTitle = '') {
    
    // First try to find the app in the current state using both process_path and window_title
    let app = appState.detectedApps.apps.find(a => 
        a.process_path === processPath && (a.window_title || '') === (windowTitle || '')
    );
    
    // If not found, try to fetch it from the server
    if (!app) {
        const params = new URLSearchParams({
            process_path: processPath,
            window_title: windowTitle || ''
        });
        fetch(`/api/detected-apps/get?${params}`)
            .then(response => response.json())
            .then(data => {
                if (data.success && data.app) {
                    app = data.app;
                    // Show edit dialog
                    showEditDialog(app);
                } else {
                    showToast('App not found');
                }
            })
            .catch(error => {
                showToast('App not found');
            });
    } else {
        // App found in state, show edit dialog
        showEditDialog(app);
    }
}

function showEditDialog(app) {
    // Store the current app being edited
    appState.editingApp = app;
    
    const populateAndShow = () => {
        // Set the input values
        const titleInput = document.getElementById('edit-app-title');
        const categoryInput = document.getElementById('edit-category-input');
        const locationInput = document.getElementById('edit-app-location');
        
        if (titleInput) {
            titleInput.value = app.app_name || '';
        }
        if (categoryInput) {
            categoryInput.value = app.twitch_category || '';
        }
        if (locationInput) {
            locationInput.value = app.process_path || '';
        }
        populateWindowTitleInputs('edit-window-title-list', app.window_title || '');

        populateEditAppListSelect(app);
        setGameDialogPathMode('edit', 'location');
        setupGameDialogPathModeToggles('edit');
        loadForegroundProcessSelect(
            document.getElementById('editCategoryProcess'),
            { selectedPath: app.process_path || '' }
        );
        
        // Clear search results
        const resultsContainer = document.getElementById('edit-category-results');
        if (resultsContainer) {
            hideEditCategorySearch();
        }
        
        // Show the modal
        const modal = document.getElementById('editCategoryModal');
        if (modal) {
            modal.style.display = 'flex';
        }
        
        // Set up event listeners
        setupEditCategoryModal();
    };

    if (!appState.detectedApps.writableLists?.length) {
        fetch('/api/apps/list')
            .then(response => response.json())
            .then(listsData => {
                appState.detectedApps.writableLists = Array.isArray(listsData)
                    ? listsData.filter(list => list.source === 'local' && list.enabled !== false && list.path)
                    : [];
                populateAndShow();
            })
            .catch(() => populateAndShow());
    } else {
        populateAndShow();
    }
}

function hideEditCategorySearch() {
    const editResults = document.getElementById('edit-category-results');
    if (editResults) {
        editResults.innerHTML = '';
        editResults.dataset.keyboardNav = 'false';
    }
    debouncedEditCategorySearch.cancel();
}

function closeEditCategoryModal() {
    const modal = document.getElementById('editCategoryModal');
    hideEditCategorySearch();
    document.removeEventListener('mousedown', handleEditCategoryModalOutsideClick);
    if (modal) {
        hideModal(modal);
    }
    restoreHomeCompactAfterEditGame();
}

function handleEditCategoryModalOutsideClick(e) {
    const modal = document.getElementById('editCategoryModal');
    if (!modal || modal.style.display !== 'flex') {
        return;
    }

    const searchContainer = document.getElementById('edit-category-input')?.closest('.search-container');
    if (searchContainer && !searchContainer.contains(e.target)) {
        hideEditCategorySearch();
    }
}

function setupEditCategoryModal() {
    const titleInput = document.getElementById('edit-app-title');
    const categoryInput = document.getElementById('edit-category-input');
    const locationInput = document.getElementById('edit-app-location');
    const browseBtn = document.getElementById('edit-browse-location-btn');
    const editResults = document.getElementById('edit-category-results');
    const cancelBtn = document.getElementById('cancelCategoryBtn');
    const saveBtn = document.getElementById('saveCategoryBtn');
    const modal = document.getElementById('editCategoryModal');
    
    if (!categoryInput) return;
    
    // Clear any existing event listeners
    categoryInput.removeEventListener('input', debouncedEditCategorySearch);
    categoryInput.removeEventListener('keydown', handleEditCategoryKeydown);
    
    // Add event listeners for category search
    categoryInput.addEventListener('input', debouncedEditCategorySearch);
    categoryInput.addEventListener('keydown', handleEditCategoryKeydown);

    document.removeEventListener('mousedown', handleEditCategoryModalOutsideClick);
    document.addEventListener('mousedown', handleEditCategoryModalOutsideClick);

    setupWindowTitleAddButton('edit-window-title-add', 'edit-window-title-list');
    
    // Add mouse event listeners to detect mouse navigation
    if (editResults) {
        editResults.onmouseenter = () => {
            editResults.dataset.keyboardNav = 'false';
            editResults.querySelectorAll('.search-result-item').forEach(item => {
                item.classList.remove('selected');
            });
        };
    }
    
    // Add Enter key handling to all input fields in the modal
    const allInputs = modal.querySelectorAll('input[type="text"], input[type="file"]');
    allInputs.forEach(input => {
        if (input !== categoryInput) {
            input.onkeydown = (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    const saveBtn = document.getElementById('saveCategoryBtn');
                    if (saveBtn) {
                        saveBtn.click();
                    }
                }
            };
        }
    });
    
    // Add browse button handler
    if (browseBtn) {
        browseBtn.onclick = () => {
            // Remove any existing file input first
            const existingInput = document.getElementById('temp-file-input');
            if (existingInput) {
                document.body.removeChild(existingInput);
            }
            
            // Create a file input element for file selection
            const fileInput = document.createElement('input');
            fileInput.id = 'temp-file-input';
            fileInput.type = 'file';
            fileInput.accept = '.exe';
            fileInput.style.display = 'none';
            
            fileInput.onchange = (event) => {
                const file = event.target.files[0];
                if (file && locationInput) {
                    // Get the full path of the selected file
                    locationInput.value = file.path || file.name;
                }
                // Clean up the temporary input
                if (document.body.contains(fileInput)) {
                    document.body.removeChild(fileInput);
                }
            };
            
            // Handle cancel case - clean up after a short delay
            fileInput.oncancel = () => {
                setTimeout(() => {
                    if (document.body.contains(fileInput)) {
                        document.body.removeChild(fileInput);
                    }
                }, 100);
            };
            
            // Add to DOM temporarily and trigger click
            document.body.appendChild(fileInput);
            fileInput.click();
        };
    }
    
    // Focus the category input
    categoryInput.focus();
    categoryInput.select();
    
    // Set up modal button handlers
    if (saveBtn) {
        saveBtn.onclick = () => {
            const newTitle = titleInput ? titleInput.value.trim() : '';
            const newCategory = categoryInput.value.trim();
            const newLocation = getGameDialogPath('edit');
            const newWindowTitle = collectWindowTitles('edit-window-title-list');
            
            if (!newCategory) {
                showToast('Please fill in category');
                return;
            }

            if (!newLocation) {
                showToast('Please select a process or enter a location');
                return;
            }

            if (appState.editingApp) {
                updateDetectedApp(
                    newLocation,
                    newTitle, // Use newTitle directly, even if empty
                    newCategory, 
                    appState.editingApp.box_art_url,
                    newWindowTitle
                );
                // Don't close modal here - let updateDetectedApp handle it based on success/failure
            }
        };
    }
    
    if (cancelBtn) {
        cancelBtn.onclick = closeEditCategoryModal;
    }
    
    // Close button
    const closeBtn = modal.querySelector('.modal-close');
    if (closeBtn) {
        closeBtn.onclick = closeEditCategoryModal;
    }

    hideEditCategorySearch();

    modal.onclick = (e) => {
        if (e.target === modal) {
            closeEditCategoryModal();
        }
    };
    
    // Focus the category input without selecting — avoids fighting dropdown clicks
    categoryInput.focus();
}

function handleEditCategorySearch() {
    const query = document.getElementById('edit-category-input')?.value.trim() || '';

    if (query.length > 2) {
        searchCategoriesForEdit(query);
    } else {
        hideEditCategorySearch();
    }
}

const debouncedEditCategorySearch = debounce(handleEditCategorySearch, 300);

function searchCategoriesForEdit(query) {

    fetch(`/api/categories?query=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(data => {
            if (data && data.length > 0) {
                renderEditCategoryResults(data);
            } else {
                hideEditCategorySearch();
            }
        })
        .catch(error => {
            hideEditCategorySearch();
        });
}

function renderEditCategoryResults(categories) {
    const editResults = document.getElementById('edit-category-results');
    if (!editResults) return;
    
    editResults.innerHTML = '';
    
    categories.forEach(category => {
        const resultItem = document.createElement('div');
        resultItem.classList.add('search-result-item');
        // Handle both string and object formats
        const categoryName = typeof category === 'string' ? category : category.name;
        resultItem.textContent = categoryName;
        resultItem.addEventListener('mousedown', (e) => {
            e.preventDefault();
        });
        resultItem.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            selectEditCategory(categoryName);
        });
        editResults.appendChild(resultItem);
    });

    positionCategoryDropdown('edit-category-input', 'edit-category-results');
}

function selectEditCategory(category) {
    const editInput = document.getElementById('edit-category-input');
    if (editInput) {
        editInput.value = category;
    }
    hideEditCategorySearch();
}

function handleEditCategoryKeydown(e) {
    const editResults = document.getElementById('edit-category-results');

    if (e.key === 'Enter') {
        e.preventDefault();
        const query = document.getElementById('edit-category-input').value.trim();
        const selectedItem = editResults?.querySelector('.search-result-item.selected');
        
        if (selectedItem) {
            document.getElementById('edit-category-input').value = selectedItem.textContent.trim();
            hideEditCategorySearch();
        } else if (query) {
            const saveBtn = document.getElementById('saveCategoryBtn');
            if (saveBtn) {
                saveBtn.click();
            }
        } else {
            const saveBtn = document.getElementById('saveCategoryBtn');
            if (saveBtn) {
                saveBtn.click();
            }
        }
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        navigateEditCategoryDropdown('down');
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        navigateEditCategoryDropdown('up');
    } else if (e.key === 'Escape') {
        if (editResults?.innerHTML) {
            hideEditCategorySearch();
        } else {
            closeEditCategoryModal();
        }
    }
}

function navigateEditCategoryDropdown(direction) {
    const editResults = document.getElementById('edit-category-results');
    if (!editResults) return;
    
    const items = editResults.querySelectorAll('.search-result-item');
    if (items.length === 0) return;
    
    // Mark that we're using keyboard navigation
    editResults.dataset.keyboardNav = 'true';
    
    const currentSelected = editResults.querySelector('.search-result-item.selected');
    let newIndex = -1;
    
    if (currentSelected) {
        // Find current index
        for (let i = 0; i < items.length; i++) {
            if (items[i] === currentSelected) {
                if (direction === 'down') {
                    newIndex = (i + 1) % items.length;
                } else {
                    newIndex = i === 0 ? items.length - 1 : i - 1;
                }
                break;
            }
        }
    } else {
        // No current selection, select first item
        newIndex = direction === 'down' ? 0 : items.length - 1;
    }
    
    // Remove previous selection
    items.forEach(item => item.classList.remove('selected'));
    
    // Add new selection
    if (newIndex >= 0 && newIndex < items.length) {
        items[newIndex].classList.add('selected');
        
        // Scroll into view if needed
        items[newIndex].scrollIntoView({ 
            block: 'nearest', 
            behavior: 'smooth' 
        });
        
        // Update the input field with the selected category
        const categoryName = items[newIndex].textContent.trim();
        const categoryInput = document.getElementById('edit-category-input');
        if (categoryInput) {
            categoryInput.value = categoryName;
        }
    }
}

function navigateAddCategoryDropdown(direction) {
    const addResults = document.getElementById('add-category-results');
    if (!addResults) return;
    
    const items = addResults.querySelectorAll('.search-result-item');
    if (items.length === 0) return;
    
    // Mark that we're using keyboard navigation
    addResults.dataset.keyboardNav = 'true';
    
    const currentSelected = addResults.querySelector('.search-result-item.selected');
    let newIndex = -1;
    
    if (currentSelected) {
        // Find current index
        for (let i = 0; i < items.length; i++) {
            if (items[i] === currentSelected) {
                if (direction === 'down') {
                    newIndex = (i + 1) % items.length;
                } else {
                    newIndex = i === 0 ? items.length - 1 : i - 1;
                }
                break;
            }
        }
    } else {
        // No current selection, select first item
        newIndex = direction === 'down' ? 0 : items.length - 1;
    }
    
    // Remove previous selection
    items.forEach(item => item.classList.remove('selected'));
    
    // Add new selection
    if (newIndex >= 0 && newIndex < items.length) {
        items[newIndex].classList.add('selected');
        
        // Scroll into view if needed
        items[newIndex].scrollIntoView({ 
            block: 'nearest', 
            behavior: 'smooth' 
        });
        
        // Update the input field with the selected category
        const categoryName = items[newIndex].textContent.trim();
        const categoryInput = document.getElementById('addCategoryName');
        if (categoryInput) {
            categoryInput.value = categoryName;
        }
    }
}

function setupRemoveAppModal() {
    
    // Use event delegation on the document to handle clicks
    document.addEventListener('click', (event) => {
        // Handle remove confirm button
        if (event.target && event.target.id === 'confirmRemoveBtn') {
            event.preventDefault();
            event.stopPropagation();
            
            if (appState.removingAppPath) {
                removeDetectedAppFromList(appState.removingAppPath, appState.removingAppWindowTitle, appState.removingAppListName);
            } else {
            }
            
            const modal = document.getElementById('removeAppModal');
            hideModal(modal);
            return;
        }
        
        // Handle remove cancel button
        if (event.target && event.target.id === 'cancelRemoveBtn') {
            event.preventDefault();
            event.stopPropagation();
            
            const modal = document.getElementById('removeAppModal');
            hideModal(modal);
            return;
        }
        
        // Handle remove modal close button
        if (event.target && event.target.closest('.modal-close') && 
            event.target.closest('#removeAppModal')) {
            event.preventDefault();
            event.stopPropagation();
            
            const modal = document.getElementById('removeAppModal');
            hideModal(modal);
            return;
        }
    });
}

async function refreshDetectedAppsAfterExclude(excludeState = null) {
    const excludingAppId = excludeState?.id ?? appState.excludingAppId;

    if (excludingAppId) {
        const existingItem = document.getElementById(excludingAppId);
        if (existingItem) {
            removeSingleDetectedAppById(excludingAppId);
        }
    }

    try {
        const data = await fetchDetectedAppsPayload();
        if (data.success) {
            appState.detectedApps.apps = sortDetectedAppsAlphabetically(data.apps || []);
            const categoriesTab = document.getElementById('categories');
            if (categoriesTab && categoriesTab.classList.contains('active') && elements.detectedAppsList) {
                renderDetectedApps();
            }
        }
    } catch (error) {
    }
}

function handleExcludeAppConfirmed() {
    const modal = document.getElementById('addToExcludedModal');

    if (!appState.excludingAppPath) {
        hideModal(modal);
        return;
    }

    const excludeState = {
        path: appState.excludingAppPath,
        name: appState.excludingAppName || '',
        category: appState.excludingAppCategory || '',
        windowTitle: appState.excludingAppWindowTitle || '',
        listName: appState.excludingAppListName || '',
        filePath: appState.excludingAppFilePath || '',
        id: appState.excludingAppId || null,
    };

    hideModal(modal);
    closeEditCategoryModal();

    fetch('/api/detected-apps/add-to-excluded', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            process_path: excludeState.path,
            app_name: excludeState.name,
            twitch_category: excludeState.category,
            window_title: excludeState.windowTitle,
            list_name: excludeState.listName,
            file_path: excludeState.filePath
        })
    })
        .then(response => response.json())
        .then(async (data) => {
            if (!data.success) {
                showToast(`Failed to add to excluded apps: ${data.error || 'Unknown error'}`);
                return;
            }

            showToast('App added to excluded apps successfully');
            await refreshDetectedAppsAfterExclude(excludeState);
            await refreshHomeEditCurrentGameButton();
        })
        .catch(error => {
            showToast('Failed to add to excluded apps');
        });
}

function setupExcludeAppModal() {
    
    // Use event delegation on the document to handle clicks
    document.addEventListener('click', (event) => {
        // Handle exclude confirm button
        if (event.target && event.target.id === 'confirmExcludeBtn') {
            event.preventDefault();
            event.stopPropagation();
            handleExcludeAppConfirmed();
            return;
        }
        
        // Handle exclude cancel button
        if (event.target && event.target.id === 'cancelExcludeBtn') {
            event.preventDefault();
            event.stopPropagation();
            
            const modal = document.getElementById('addToExcludedModal');
            hideModal(modal);
            return;
        }
        
        // Handle exclude modal close button
        if (event.target && event.target.closest('.modal-close') && 
            event.target.closest('#addToExcludedModal')) {
            event.preventDefault();
            event.stopPropagation();
            
            const modal = document.getElementById('addToExcludedModal');
            hideModal(modal);
            return;
        }
    });
}

function updateDetectedApp(processPath, appName, twitchCategory, boxArtUrl, windowTitle) {
    
    // Check if this is an edit (we have an existing app being edited)
    const isEdit = appState.editingApp && appState.editingApp.process_path;
    
    if (isEdit) {
        // Check if this is a manually entered category (not selected from dropdown)
        const isManuallyEntered = !document.querySelector('.search-result-item.selected');
        
        if (isManuallyEntered) {
            // Validate the category exists on Twitch
            validateAndUpdateCategory(processPath, appName, twitchCategory, boxArtUrl, windowTitle);
            return;
        }
        
        // This is an edit - move list if needed, then save changes
        submitDetectedAppEdit(processPath, appName, twitchCategory, boxArtUrl, windowTitle)
        .then(({ data, moveResult }) => {
            if (data.status === 'success') {
                completeDetectedAppEdit(processPath, appName, twitchCategory, boxArtUrl, windowTitle, moveResult);
            } else {
                showToast(`Failed to update app: ${data.error || data.message || 'Unknown error'}`);
            }
        })
        .catch(error => {
            showToast(error.message || 'Failed to update app');
        });
    } else {
        // This is a new detection - use the existing flow
        // First, get the box art for the new category
        fetch(`/api/categories?query=${encodeURIComponent(twitchCategory)}`)
            .then(response => response.json())
            .then(categories => {
                // Find the exact category match to get box art
                const exactMatch = categories.find(cat => {
                    const catName = typeof cat === 'string' ? cat : cat.name;
                    return catName.toLowerCase() === twitchCategory.toLowerCase();
                });
                let newBoxArtUrl = boxArtUrl; // Keep existing if no match found
                
                if (exactMatch) {
                    // Try to get box art for this category
                    return fetch('/api/update-category', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                        body: JSON.stringify({
                            category_name: twitchCategory
                        })
                    });
                } else {
                    // No exact match, proceed with existing box art
                    return Promise.resolve({ json: () => Promise.resolve({ box_art_url: boxArtUrl }) });
                }
            })
            .then(response => response.json())
            .then(categoryData => {
                return fetch('/api/detected-apps/save', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        process_path: processPath,
                        app_name: appName,
                        twitch_category: twitchCategory,
                        window_title: windowTitle || ''
                    })
                });
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success' || data.success) {
                    showToast('App updated successfully');
                    addSingleDetectedApp(processPath, windowTitle); // Add new category dynamically
                } else {
                    showToast(`Failed to update app: ${data.error || data.message || 'Unknown error'}`);
                }
            })
            .catch(error => {
                showToast('Failed to update app');
            });
    }
}

function addDetectedAppToExcludedById(appId) {
    
    const appItem = document.getElementById(appId);
    if (!appItem) {
        showToast('App not found');
        return;
    }
    
    const processPath = appItem.getAttribute('data-process-path');
    const windowTitle = appItem.getAttribute('data-window-title');
    const listName = appItem.getAttribute('data-list-name');
    const filePath = appItem.getAttribute('data-file-path');
    
    // Find the app in the state to get all identifying fields
    const app = appState.detectedApps.apps.find(a => 
        a.process_path === processPath && (a.window_title || '') === (windowTitle || '')
    );
    
    if (!app) {
        showToast('App not found in current state');
        return;
    }
    
    // Store ALL identifying fields for the confirmation
    appState.excludingAppPath = processPath;
    appState.excludingAppName = app.app_name || '';
    appState.excludingAppCategory = app.twitch_category || '';
    appState.excludingAppWindowTitle = windowTitle;
    appState.excludingAppListName = listName;
    appState.excludingAppFilePath = filePath || app.file_path || '';
    appState.excludingAppId = appId; // Store the ID for later reference
    
    
    // Show the exclude modal
    const modal = document.getElementById('addToExcludedModal');
    const message = document.getElementById('excludeAppMessage');
    if (modal && message) {
        message.textContent = `Are you sure you want to add "${app.app_name || app.twitch_category}" to the excluded apps list?`;
        modal.style.display = 'flex';
    } else {
    }
}

function addDetectedAppToExcluded(processPath, windowTitle, listName) {
    
    // Find the app data to get all identifying fields
    const app = appState.detectedApps.apps.find(a => 
        a.process_path === processPath && (a.window_title || '') === (windowTitle || '')
    );
    
    if (!app) {
        showToast('App not found');
        return;
    }
    
    // Store ALL identifying fields for the confirmation
    appState.excludingAppPath = processPath;
    appState.excludingAppName = app.app_name || '';
    appState.excludingAppCategory = app.twitch_category || '';
    appState.excludingAppWindowTitle = windowTitle;
    appState.excludingAppListName = listName;
    appState.excludingAppFilePath = app.file_path || '';
    
    // Show the exclude modal
    const modal = document.getElementById('addToExcludedModal');
    if (modal) {
        modal.style.display = 'flex';
    }
    
}

function removeDetectedAppById(appId) {
    
    const appItem = document.getElementById(appId);
    if (!appItem) {
        showToast('App not found');
        return;
    }
    
    const processPath = appItem.getAttribute('data-process-path');
    const windowTitle = appItem.getAttribute('data-window-title');
    const listName = appItem.getAttribute('data-list-name');
    
    // Find the app in the state to get all identifying fields
    const app = appState.detectedApps.apps.find(a => 
        a.process_path === processPath && (a.window_title || '') === (windowTitle || '')
    );
    
    if (!app) {
        showToast('App not found in current state');
        return;
    }
    
    // Store ALL identifying fields for the confirmation
    appState.removingAppPath = processPath;
    appState.removingAppName = app.app_name || '';
    appState.removingAppCategory = app.twitch_category || '';
    appState.removingAppWindowTitle = windowTitle;
    appState.removingAppListName = listName;
    appState.removingAppId = appId; // Store the ID for later reference
    
    
    // Show the remove modal
    const modal = document.getElementById('removeAppModal');
    const message = document.getElementById('removeAppMessage');
    if (modal && message) {
        message.textContent = `Are you sure you want to remove "${app.app_name || app.twitch_category}" from the ${listName} list?`;
        modal.style.display = 'flex';
    } else {
    }
}

function removeDetectedAppFromList(processPath, windowTitle, listName) {
    
    fetch('/api/detected-apps/remove', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            process_path: processPath,
            app_name: appState.removingAppName || '',
            twitch_category: appState.removingAppCategory || '',
            window_title: windowTitle || '',
            list_name: listName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('App removed successfully');
            // Remove the single element dynamically using app ID
            removeSingleDetectedAppById(appState.removingAppId);
        } else {
            showToast(`Failed to remove app: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(error => {
        showToast('Failed to remove app');
    });
}

// Function to save a detected app (called from game detection)
function saveDetectedApp(processPath, appName, twitchCategory, boxArtUrl, windowTitle) {
    
    fetch('/api/detected-apps/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            process_path: processPath,
            app_name: appName,
            twitch_category: twitchCategory,
            window_title: windowTitle || ''
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (data.skipped) {
                return;
            }
            // Add the new detected app dynamically if we're on the categories tab
            if (appState.activeTab === 'categories') {
                addSingleDetectedApp(processPath, windowTitle, appName, twitchCategory, boxArtUrl);
            }
        } else {
        }
    })
    .catch(error => {
    });
}

// ============================================================================
// Title Presets
// ============================================================================

const titlePresetsState = {
    presets: [],            // [{title, games, has_assignments, is_favorite}]
    defaultTitle: null,
    favoriteTitles: new Set(),
    selectedTitle: null,
    editing: null,          // preset title being edited, null = add mode
    saveContext: null,      // {assignAfter: bool, assignGame: app|null}
    assignTitle: null,      // preset title the assign modal is working on
    assignSelection: new Set(),
    assignInitial: new Set(),   // games assigned to the preset when the modal opened
    gameModalApp: null,     // app shown in the per-game stream title modal
    gameModalSelected: null,
    existingSelected: null,
};

function assignGamePayload(app) {
    return {
        process_path: app.process_path || '',
        app_name: app.app_name || '',
        twitch_category: app.twitch_category || '',
        window_title: app.window_title || '',
    };
}

function gameDisplayName(app) {
    return app.app_name || app.twitch_category || app.process_path || 'Unknown game';
}

const TITLE_PRESET_GROUP_ORDER = ['default', 'favorites', 'unassigned', 'assigned'];

function getTitlePresetGroup(preset) {
    if (preset.title === titlePresetsState.defaultTitle) {
        return 'default';
    }
    if (titlePresetsState.favoriteTitles.has(preset.title)) {
        return 'favorites';
    }
    if (!preset.has_assignments) {
        return 'unassigned';
    }
    return 'assigned';
}

function groupTitlePresetsForDisplay(presets) {
    const grouped = {
        default: [],
        favorites: [],
        unassigned: [],
        assigned: [],
    };
    presets.forEach(preset => {
        grouped[getTitlePresetGroup(preset)].push(preset);
    });
    TITLE_PRESET_GROUP_ORDER.forEach(groupKey => {
        grouped[groupKey].sort((a, b) => a.title.localeCompare(b.title, undefined, { sensitivity: 'base' }));
    });
    return grouped;
}

function loadTitlePresets() {
    return fetch('/api/title-presets/list')
        .then(response => response.json())
        .then(data => {
            titlePresetsState.presets = data.presets || [];
            titlePresetsState.defaultTitle = data.default_title || null;
            titlePresetsState.favoriteTitles = new Set(data.favorite_titles || []);
            if (!titlePresetsState.presets.some(p => p.title === titlePresetsState.selectedTitle)) {
                titlePresetsState.selectedTitle = null;
            }
            renderTitlePresetList();
        })
        .catch(() => {});
}

function buildAssignedGamesTooltip(preset) {
    const games = (preset.games || []).filter(game => game.resolved);
    if (!games.length) {
        return '';
    }

    const seen = new Set();
    const names = [];
    games.forEach(game => {
        const name = gameDisplayName(game);
        if (!name || seen.has(name)) {
            return;
        }
        seen.add(name);
        names.push(name);
    });

    if (!names.length) {
        return '';
    }

    const items = names.map(name => `- ${name}`).join('\n');
    return `Assigned to:\n${items}`;
}

function appendTitlePresetBadges(row, preset) {
    const hasDefault = preset.title === titlePresetsState.defaultTitle;
    const hasFavorite = titlePresetsState.favoriteTitles.has(preset.title);
    const hasAssignments = preset.has_assignments;
    if (!hasDefault && !hasFavorite && !hasAssignments) {
        return;
    }

    const badges = document.createElement('span');
    badges.className = 'title-preset-badges';

    if (hasFavorite) {
        const heart = document.createElement('span');
        heart.className = 'icon icon-heart icon-xs';
        heart.title = 'Favorite';
        heart.setAttribute('aria-hidden', 'true');
        badges.appendChild(heart);
    }

    if (hasDefault) {
        const star = document.createElement('span');
        star.className = 'icon icon-star icon-xs';
        star.title = 'Default title';
        star.setAttribute('aria-hidden', 'true');
        badges.appendChild(star);
    }

    if (hasAssignments) {
        const puzzle = document.createElement('span');
        puzzle.className = 'icon icon-puzzle-piece icon-xs';
        puzzle.setAttribute('aria-hidden', 'true');
        puzzle.title = buildAssignedGamesTooltip(preset) || 'Assigned to games';
        badges.appendChild(puzzle);
    }

    row.appendChild(badges);
}

function appendTitlePresetRow(list, preset) {
    const row = document.createElement('div');
    row.className = 'title-preset-row';
    if (preset.title === titlePresetsState.selectedTitle) {
        row.classList.add('selected');
    }

    const text = document.createElement('span');
    text.className = 'title-preset-text';
    text.textContent = preset.title;
    text.title = preset.title;
    row.appendChild(text);

    appendTitlePresetBadges(row, preset);

    row.onclick = (event) => {
        event.stopPropagation();
        titlePresetsState.selectedTitle = preset.title;
        list.querySelectorAll('.title-preset-row.selected').forEach(selectedRow => {
            selectedRow.classList.remove('selected');
        });
        row.classList.add('selected');
        updateTitlePresetButtons();
    };
    row.ondblclick = () => applyTitlePreset(preset.title);
    list.appendChild(row);
}

function renderTitlePresetList() {
    const list = document.getElementById('title-presets-list');
    if (!list) return;

    if (!titlePresetsState.presets.length) {
        list.innerHTML = '<div class="title-preset-empty">No title presets yet. Click "Add New" to create one.</div>';
        updateTitlePresetButtons();
        return;
    }

    list.innerHTML = '';
    const grouped = groupTitlePresetsForDisplay(titlePresetsState.presets);
    TITLE_PRESET_GROUP_ORDER.forEach(groupKey => {
        grouped[groupKey].forEach(preset => appendTitlePresetRow(list, preset));
    });
    updateTitlePresetButtons();
}

function clearTitlePresetSelection() {
    if (!titlePresetsState.selectedTitle) {
        return;
    }
    titlePresetsState.selectedTitle = null;
    renderTitlePresetList();
}

function updateTitlePresetButtons() {
    const hasSelection = !!titlePresetsState.selectedTitle;
    const selectedTitle = titlePresetsState.selectedTitle;
    const isDefault = hasSelection && selectedTitle === titlePresetsState.defaultTitle;
    const isFavorite = hasSelection && titlePresetsState.favoriteTitles.has(selectedTitle);
    const applyBtn = document.getElementById('presetApplyBtn');
    const editBtn = document.getElementById('presetEditBtn');
    const assignBtn = document.getElementById('presetAssignBtn');
    const favoriteBtn = document.getElementById('presetFavoriteBtn');
    const defaultBtn = document.getElementById('presetDefaultBtn');
    const removeBtn = document.getElementById('presetRemoveBtn');
    if (applyBtn) applyBtn.disabled = !hasSelection;
    if (editBtn) editBtn.disabled = !hasSelection;
    if (assignBtn) assignBtn.disabled = !hasSelection;
    if (removeBtn) removeBtn.disabled = !hasSelection;
    if (favoriteBtn) {
        favoriteBtn.disabled = !hasSelection;
        favoriteBtn.title = isFavorite ? 'Remove from favorites' : 'Add to favorites';
    }
    if (defaultBtn) {
        defaultBtn.disabled = !hasSelection;
        defaultBtn.title = isDefault ? 'Clear default' : 'Set as default';
        defaultBtn.classList.toggle('active', isDefault);
    }
}

function applyTitlePreset(title) {
    fetch('/api/title-presets/apply', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            streamTitleUpdated(data);
            showToast('Stream title updated');
        } else {
            showToast(`Failed to apply title: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(error => {
        showToast('Failed to apply title');
    });
}

function toggleDefaultTitle() {
    const title = titlePresetsState.selectedTitle;
    if (!title) return;

    const isDefault = title === titlePresetsState.defaultTitle;
    const endpoint = isDefault ? '/api/title-presets/clear-default' : '/api/title-presets/set-default';
    const payload = isDefault ? {} : { title };

    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            titlePresetsState.defaultTitle = data.default_title || null;
            renderTitlePresetList();
            showToast(isDefault ? 'Default title cleared' : 'Default title set');
        } else {
            showToast(`Failed to update default: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(() => {});
}

function toggleFavoriteTitle() {
    const title = titlePresetsState.selectedTitle;
    if (!title) return;

    const isFavorite = titlePresetsState.favoriteTitles.has(title);
    const endpoint = isFavorite ? '/api/title-presets/unfavorite' : '/api/title-presets/favorite';

    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            titlePresetsState.favoriteTitles = new Set(data.favorite_titles || []);
            renderTitlePresetList();
            showToast(isFavorite ? 'Removed from favorites' : 'Added to favorites');
        } else {
            showToast(`Failed to update favorite: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(() => {});
}

// Called from the backend when a preset is auto-applied on category change
const CATEGORY_TITLE_PLACEHOLDER = '%cat';

function resolveTitleText(template, category) {
    return (template || '').replaceAll(CATEGORY_TITLE_PLACEHOLDER, category || '');
}

function setStreamTitleState(template, resolved) {
    appState.titleTemplate = template || resolved || '';
    appState.currentTitle = resolved || resolveTitleText(template, getCurrentCategory()) || '';
    if (elements.titleLabel) {
        elements.titleLabel.textContent = appState.currentTitle;
    }
}

function refreshTitleDisplay() {
    const template = appState.titleTemplate || '';
    if (!template.includes(CATEGORY_TITLE_PLACEHOLDER)) {
        return;
    }
    const resolved = resolveTitleText(template, getCurrentCategory());
    appState.currentTitle = resolved;
    if (elements.titleLabel) {
        elements.titleLabel.textContent = resolved;
    }
}

function streamTitleUpdated(payload) {
    if (typeof payload === 'string') {
        setStreamTitleState(payload, payload);
        return;
    }
    const template = payload.title_template ?? payload.resolved_title ?? '';
    const resolved = payload.resolved_title ?? resolveTitleText(template, getCurrentCategory());
    setStreamTitleState(template, resolved);
}
window.streamTitleUpdated = streamTitleUpdated;

function removeTitlePreset(title, onDone = null) {
    showConfirmationModal(
        'Remove Title Preset',
        `Remove the stream title "${escapeHtml(title)}" entirely?`,
        () => {
            fetch('/api/title-presets/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showToast('Title preset removed');
                    loadTitlePresets().then(() => { if (onDone) onDone(); });
                } else {
                    showToast(`Failed to remove: ${data.error || 'Unknown error'}`);
                }
            })
            .catch(() => {});
        },
        null,
        'Remove'
    );
}

// --- Add / Edit modal --------------------------------------------------------

function openTitlePresetModal(existingTitle = null, saveContext = null) {
    titlePresetsState.editing = existingTitle;
    titlePresetsState.saveContext = saveContext || {};

    const header = document.getElementById('titlePresetModalHeader');
    const input = document.getElementById('titlePresetInput');
    const saveAssignBtn = document.getElementById('titlePresetSaveAssignBtn');
    const importBtn = document.getElementById('titlePresetImportBtn');

    if (header) header.textContent = existingTitle ? 'Edit Title Preset' : 'Add Title Preset';
    if (input) input.value = existingTitle || '';
    // Save & Assign only makes sense when creating from the home screen
    if (saveAssignBtn) {
        saveAssignBtn.style.display = (!existingTitle && !titlePresetsState.saveContext.assignGame) ? '' : 'none';
    }
    if (importBtn) {
        importBtn.style.display = existingTitle ? 'none' : '';
    }
    updateTitlePresetSaveButtons();

    showModal('titlePresetModal');
    if (input) input.focus();
}

function importCurrentStreamTitleToPreset() {
    const input = document.getElementById('titlePresetInput');
    if (!input) {
        return;
    }
    const currentTitle = (appState.titleTemplate || appState.currentTitle || elements.titleLabel?.textContent || '').trim();
    if (!currentTitle || currentTitle === 'Loading...') {
        return;
    }
    input.value = currentTitle;
    updateTitlePresetSaveButtons();
    input.focus();
}

function updateTitlePresetSaveButtons() {
    const isEmpty = !(document.getElementById('titlePresetInput')?.value || '').trim();
    const saveBtn = document.getElementById('titlePresetSaveBtn');
    const saveAssignBtn = document.getElementById('titlePresetSaveAssignBtn');
    if (saveBtn) saveBtn.disabled = isEmpty;
    if (saveAssignBtn) saveAssignBtn.disabled = isEmpty;
}

function saveTitlePreset(assignAfter) {
    const input = document.getElementById('titlePresetInput');
    const newTitle = (input?.value || '').trim();
    if (!newTitle) {
        showToast('Title cannot be empty');
        return;
    }

    const editing = titlePresetsState.editing;
    const endpoint = editing ? '/api/title-presets/rename' : '/api/title-presets/add';
    const payload = editing ? { old_title: editing, new_title: newTitle } : { title: newTitle };

    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            showToast(data.error || 'Failed to save title preset');
            return;
        }
        hideModal('titlePresetModal');
        const context = titlePresetsState.saveContext || {};
        if (titlePresetsState.selectedTitle === editing) {
            titlePresetsState.selectedTitle = newTitle;
        }
        loadTitlePresets().then(() => {
            if (context.assignGame) {
                // Created from the per-game modal: assign to that game right away
                assignGamesToPreset(newTitle, [context.assignGame], () => refreshGameTitleModal());
            } else if (assignAfter) {
                openAssignTitleModal(newTitle);
            }
            refreshGameTitleModal();
        });
    })
    .catch(() => {});
}

// --- Assign to game modal ----------------------------------------------------

function openAssignTitleModal(presetTitle) {
    titlePresetsState.assignTitle = presetTitle;

    // Pre-select the games already assigned to this preset so they list first
    // and can be clicked to un-assign them.
    const preset = titlePresetsState.presets.find(p => p.title === presetTitle);
    const assignedKeys = new Set(
        (preset?.games || [])
            .filter(game => game.resolved)
            .map(assignGameKey)
    );
    titlePresetsState.assignInitial = assignedKeys;
    titlePresetsState.assignSelection = new Set(assignedKeys);

    const nameEl = document.getElementById('assignTitleName');
    if (nameEl) nameEl.textContent = presetTitle;
    const filter = document.getElementById('assignTitleFilter');
    if (filter) filter.value = '';

    const render = () => renderAssignGameList();
    if (appState.detectedApps.apps.length) {
        render();
    } else {
        fetchDetectedAppsPayload()
            .then(data => {
                if (data.success) {
                    setDetectedAppsState(data.apps || []);
                }
                render();
            })
            .catch(() => render());
    }

    showModal('assignTitleModal');
}

function assignGameKey(app) {
    return `${app.process_path}|${app.twitch_category}|${app.window_title}|${app.app_name}`;
}

function renderAssignGameList() {
    const list = document.getElementById('assignGameList');
    if (!list) return;

    const filterText = (document.getElementById('assignTitleFilter')?.value || '').toLowerCase();
    const initial = titlePresetsState.assignInitial || new Set();
    const apps = appState.detectedApps.apps
        .filter(app => {
            if (!filterText) return true;
            return gameDisplayName(app).toLowerCase().includes(filterText)
                || (app.twitch_category || '').toLowerCase().includes(filterText)
                || (app.process_path || '').toLowerCase().includes(filterText);
        })
        .sort((a, b) => {
            const aAssigned = initial.has(assignGameKey(a)) ? 0 : 1;
            const bAssigned = initial.has(assignGameKey(b)) ? 0 : 1;
            return aAssigned - bAssigned;
        });

    list.innerHTML = '';
    if (!apps.length) {
        list.innerHTML = '<div class="title-preset-empty">No games found.</div>';
        updateAssignConfirmButton();
        return;
    }

    apps.forEach(app => {
        const key = assignGameKey(app);
        const row = document.createElement('div');
        row.className = 'assign-game-row';
        if (titlePresetsState.assignSelection.has(key)) {
            row.classList.add('selected');
        }

        const boxArt = document.createElement('div');
        boxArt.className = 'box-art-cover box-art-cover--assign assign-game-boxart';
        boxArt.innerHTML = '<div class="box-art-placeholder" aria-hidden="true"></div>';
        if (isUsableBoxArtUrl(app.box_art_url)) {
            const img = document.createElement('img');
            img.className = 'box-art-image';
            img.alt = app.twitch_category || '';
            boxArt.appendChild(img);
            setBoxArtImage(img, app.box_art_url);
        }

        const info = document.createElement('div');
        info.className = 'assign-game-info';
        const name = document.createElement('div');
        name.className = 'assign-game-name';
        name.textContent = gameDisplayName(app);
        const category = document.createElement('div');
        category.className = 'assign-game-category';
        category.textContent = app.twitch_category || '';
        info.appendChild(name);
        info.appendChild(category);

        row.appendChild(boxArt);
        row.appendChild(info);
        row.onclick = () => {
            if (titlePresetsState.assignSelection.has(key)) {
                titlePresetsState.assignSelection.delete(key);
                row.classList.remove('selected');
            } else {
                titlePresetsState.assignSelection.add(key);
                row.classList.add('selected');
            }
            updateAssignConfirmButton();
        };
        list.appendChild(row);
    });
    updateAssignConfirmButton();
}

function getAssignSelectionDiff() {
    const initial = titlePresetsState.assignInitial || new Set();
    const selection = titlePresetsState.assignSelection;
    const toAssign = appState.detectedApps.apps.filter(app => {
        const key = assignGameKey(app);
        return selection.has(key) && !initial.has(key);
    });
    const toUnassign = appState.detectedApps.apps.filter(app => {
        const key = assignGameKey(app);
        return !selection.has(key) && initial.has(key);
    });
    return { toAssign, toUnassign };
}

function updateAssignConfirmButton() {
    const btn = document.getElementById('assignTitleConfirmBtn');
    if (!btn) return;
    const { toAssign, toUnassign } = getAssignSelectionDiff();
    btn.disabled = toAssign.length === 0 && toUnassign.length === 0;
}

function confirmAssignTitle() {
    const { toAssign, toUnassign } = getAssignSelectionDiff();
    if (!toAssign.length && !toUnassign.length) return;

    const unassignAll = () => Promise.all(
        toUnassign.map(app =>
            fetch('/api/title-presets/unassign', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ game: assignGamePayload(app) })
            }).then(response => response.json())
        )
    );

    const finish = () => {
        hideModal('assignTitleModal');
        loadTitlePresets();
        refreshGameTitleModal();
    };

    if (toAssign.length) {
        assignGamesToPreset(titlePresetsState.assignTitle, toAssign, () => {
            if (toUnassign.length) {
                unassignAll().then(finish).catch(error => {
                    finish();
                });
            } else {
                finish();
            }
        });
    } else {
        unassignAll()
            .then(() => {
                showToast('Assignments updated');
                finish();
            })
            .catch(error => {
                finish();
            });
    }
}

function assignGamesToPreset(presetTitle, apps, onSuccess = null, force = false) {
    fetch('/api/title-presets/assign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            title: presetTitle,
            games: apps.map(assignGamePayload),
            force
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Title assigned');
            loadTitlePresets();
            if (onSuccess) onSuccess();
            return;
        }
        if (data.conflicts && data.conflicts.length) {
            const lines = data.conflicts.map(c =>
                `${escapeHtml(gameDisplayName(c.game))} is already assigned to "${escapeHtml(c.assigned_to)}"`
            );
            showConfirmationModal(
                'Re-assign Stream Title',
                `${lines.join('<br>')}<br><br>Re-assign to "${escapeHtml(presetTitle)}"?`,
                () => assignGamesToPreset(presetTitle, apps, onSuccess, true),
                null,
                'Re-assign'
            );
            return;
        }
        showToast(`Failed to assign: ${data.error || 'Unknown error'}`);
    })
    .catch(() => {});
}

function openExcludeAppFromEditDialog() {
    const app = appState.editingApp;
    if (!app) {
        showToast('No game selected');
        return;
    }

    const locationInput = document.getElementById('edit-app-location');
    const titleInput = document.getElementById('edit-app-title');
    const categoryInput = document.getElementById('edit-category-input');
    const windowTitle = collectWindowTitles('edit-window-title-list');

    const processPath = getGameDialogPath('edit') || app.process_path || '';
    const appName = (titleInput?.value || '').trim() || app.app_name || '';
    const twitchCategory = (categoryInput?.value || '').trim() || app.twitch_category || '';

    appState.excludingAppPath = processPath;
    appState.excludingAppName = appName;
    appState.excludingAppCategory = twitchCategory;
    appState.excludingAppWindowTitle = windowTitle;
    appState.excludingAppListName = app.list_name || '';
    appState.excludingAppFilePath = app.file_path || '';
    appState.excludingAppId = appState.editingAppId || null;

    const modal = document.getElementById('addToExcludedModal');
    const message = document.getElementById('excludeAppMessage');
    if (!modal || !message) {
        showToast('Could not open exclude dialog');
        return;
    }

    const displayName = appName || twitchCategory || processPath;
    message.textContent = `Are you sure you want to add "${displayName}" to the excluded apps list?`;
    showModal(modal);
}

// --- Per-game stream title modal ----------------------------------------------

function openGameTitleModal() {
    const app = appState.editingApp;
    if (!app) {
        showToast('No game selected');
        return;
    }
    titlePresetsState.gameModalApp = app;
    titlePresetsState.gameModalSelected = null;

    const nameEl = document.getElementById('gameTitleGameName');
    if (nameEl) nameEl.textContent = gameDisplayName(app);

    showModal('gameTitleModal');
    refreshGameTitleModal();
}

function refreshGameTitleModal() {
    const modal = document.getElementById('gameTitleModal');
    const app = titlePresetsState.gameModalApp;
    if (!modal || modal.style.display !== 'flex' || !app) return;

    const params = new URLSearchParams({
        process_path: app.process_path || '',
        twitch_category: app.twitch_category || '',
        window_title: app.window_title || '',
        app_name: app.app_name || '',
    });
    fetch(`/api/title-presets/for-game?${params}`)
        .then(response => response.json())
        .then(data => renderGameTitleList(data.title || null))
        .catch(() => {});
}

function renderGameTitleList(assignedTitle) {
    const list = document.getElementById('game-title-presets-list');
    if (!list) return;

    titlePresetsState.gameModalAssigned = assignedTitle;
    if (titlePresetsState.gameModalSelected !== assignedTitle) {
        titlePresetsState.gameModalSelected = null;
    }

    list.innerHTML = '';
    if (!assignedTitle) {
        list.innerHTML = '<div class="title-preset-empty">No stream title assigned to this game.</div>';
    } else {
        const row = document.createElement('div');
        row.className = 'title-preset-row';
        if (titlePresetsState.gameModalSelected === assignedTitle) {
            row.classList.add('selected');
        }

        const text = document.createElement('span');
        text.className = 'title-preset-text';
        text.textContent = assignedTitle;
        text.title = assignedTitle;
        row.appendChild(text);

        row.onclick = (event) => {
            event.stopPropagation();
            titlePresetsState.gameModalSelected = assignedTitle;
            list.querySelectorAll('.title-preset-row.selected').forEach(selectedRow => {
                selectedRow.classList.remove('selected');
            });
            row.classList.add('selected');
            updateGameTitleButtons();
        };
        list.appendChild(row);
    }
    updateGameTitleButtons();
}

function updateGameTitleButtons() {
    const hasSelection = !!titlePresetsState.gameModalSelected;
    const editBtn = document.getElementById('gameTitleEditBtn');
    const unassignBtn = document.getElementById('gameTitleUnassignBtn');
    const removeBtn = document.getElementById('gameTitleRemoveBtn');
    if (editBtn) editBtn.disabled = !hasSelection;
    if (unassignBtn) unassignBtn.disabled = !hasSelection;
    if (removeBtn) removeBtn.disabled = !hasSelection;
}

function unassignGameTitle() {
    const app = titlePresetsState.gameModalApp;
    if (!app) return;
    fetch('/api/title-presets/unassign', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ game: assignGamePayload(app) })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Title un-assigned');
            loadTitlePresets();
            refreshGameTitleModal();
        } else {
            showToast(`Failed to un-assign: ${data.error || 'Unknown error'}`);
        }
    })
    .catch(() => {});
}

// --- Add existing title picker -------------------------------------------------

function openExistingTitleModal() {
    titlePresetsState.existingSelected = null;
    loadTitlePresets().then(() => {
        renderExistingTitleList();
        showModal('existingTitleModal');
    });
}

function renderExistingTitleList() {
    const list = document.getElementById('existing-title-list');
    if (!list) return;

    const assigned = titlePresetsState.gameModalAssigned;
    const candidates = titlePresetsState.presets.filter(p => p.title !== assigned);

    list.innerHTML = '';
    if (!candidates.length) {
        list.innerHTML = '<div class="title-preset-empty">No other title presets available.</div>';
    } else {
        candidates.forEach(preset => {
            const row = document.createElement('div');
            row.className = 'title-preset-row';
            if (titlePresetsState.existingSelected === preset.title) {
                row.classList.add('selected');
            }
            row.textContent = preset.title;
            row.title = preset.title;
            row.onclick = () => {
                titlePresetsState.existingSelected = preset.title;
                renderExistingTitleList();
            };
            row.ondblclick = () => {
                titlePresetsState.existingSelected = preset.title;
                confirmExistingTitleAssign();
            };
            list.appendChild(row);
        });
    }

    const assignBtn = document.getElementById('existingTitleAssignBtn');
    if (assignBtn) assignBtn.disabled = !titlePresetsState.existingSelected;
}

function confirmExistingTitleAssign() {
    const app = titlePresetsState.gameModalApp;
    const title = titlePresetsState.existingSelected;
    if (!app || !title) return;
    assignGamesToPreset(title, [app], () => {
        hideModal('existingTitleModal');
        refreshGameTitleModal();
    });
}

// --- Setup ---------------------------------------------------------------------

function setupTitlePresets() {
    const applyBtn = document.getElementById('presetApplyBtn');
    const editBtn = document.getElementById('presetEditBtn');
    const addBtn = document.getElementById('presetAddBtn');
    const assignBtn = document.getElementById('presetAssignBtn');
    const favoriteBtn = document.getElementById('presetFavoriteBtn');
    const defaultBtn = document.getElementById('presetDefaultBtn');
    const removeBtn = document.getElementById('presetRemoveBtn');

    if (applyBtn) applyBtn.onclick = () => {
        if (titlePresetsState.selectedTitle) applyTitlePreset(titlePresetsState.selectedTitle);
    };
    if (editBtn) editBtn.onclick = () => {
        if (titlePresetsState.selectedTitle) openTitlePresetModal(titlePresetsState.selectedTitle);
    };
    if (addBtn) addBtn.onclick = () => openTitlePresetModal();
    if (assignBtn) assignBtn.onclick = () => {
        if (titlePresetsState.selectedTitle) openAssignTitleModal(titlePresetsState.selectedTitle);
    };
    if (favoriteBtn) favoriteBtn.onclick = toggleFavoriteTitle;
    if (defaultBtn) defaultBtn.onclick = toggleDefaultTitle;
    if (removeBtn) removeBtn.onclick = () => {
        if (titlePresetsState.selectedTitle) removeTitlePreset(titlePresetsState.selectedTitle);
    };

    // Add / Edit modal
    const presetImportBtn = document.getElementById('titlePresetImportBtn');
    const presetSaveBtn = document.getElementById('titlePresetSaveBtn');
    const presetSaveAssignBtn = document.getElementById('titlePresetSaveAssignBtn');
    const presetInput = document.getElementById('titlePresetInput');
    if (presetImportBtn) presetImportBtn.onclick = importCurrentStreamTitleToPreset;
    if (presetSaveBtn) presetSaveBtn.onclick = () => saveTitlePreset(false);
    if (presetSaveAssignBtn) presetSaveAssignBtn.onclick = () => saveTitlePreset(true);
    if (presetInput) {
        presetInput.oninput = updateTitlePresetSaveButtons;
        presetInput.onkeydown = (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                saveTitlePreset(false);
            }
        };
    }

    // Assign modal
    const assignCancelBtn = document.getElementById('assignTitleCancelBtn');
    const assignConfirmBtn = document.getElementById('assignTitleConfirmBtn');
    const assignFilter = document.getElementById('assignTitleFilter');
    if (assignCancelBtn) assignCancelBtn.onclick = () => hideModal('assignTitleModal');
    if (assignConfirmBtn) assignConfirmBtn.onclick = confirmAssignTitle;
    if (assignFilter) assignFilter.oninput = () => renderAssignGameList();

    // Per-game modal
    const editStreamTitleBtn = document.getElementById('editStreamTitleBtn');
    const editExcludeAppBtn = document.getElementById('editExcludeAppBtn');
    const gameTitleCloseBtn = document.getElementById('gameTitleCloseBtn');
    const gameTitleAddNewBtn = document.getElementById('gameTitleAddNewBtn');
    const gameTitleAddExistingBtn = document.getElementById('gameTitleAddExistingBtn');
    const gameTitleEditBtn = document.getElementById('gameTitleEditBtn');
    const gameTitleUnassignBtn = document.getElementById('gameTitleUnassignBtn');
    const gameTitleRemoveBtn = document.getElementById('gameTitleRemoveBtn');

    if (editStreamTitleBtn) editStreamTitleBtn.onclick = openGameTitleModal;
    if (editExcludeAppBtn) editExcludeAppBtn.onclick = openExcludeAppFromEditDialog;
    if (gameTitleCloseBtn) gameTitleCloseBtn.onclick = () => hideModal('gameTitleModal');
    if (gameTitleAddNewBtn) gameTitleAddNewBtn.onclick = () => {
        openTitlePresetModal(null, { assignGame: titlePresetsState.gameModalApp });
    };
    if (gameTitleAddExistingBtn) gameTitleAddExistingBtn.onclick = openExistingTitleModal;
    if (gameTitleEditBtn) gameTitleEditBtn.onclick = () => {
        if (titlePresetsState.gameModalSelected) openTitlePresetModal(titlePresetsState.gameModalSelected);
    };
    if (gameTitleUnassignBtn) gameTitleUnassignBtn.onclick = unassignGameTitle;
    if (gameTitleRemoveBtn) gameTitleRemoveBtn.onclick = () => {
        if (titlePresetsState.gameModalSelected) {
            removeTitlePreset(titlePresetsState.gameModalSelected, () => refreshGameTitleModal());
        }
    };

    // Existing title picker modal
    const existingCancelBtn = document.getElementById('existingTitleCancelBtn');
    const existingAssignBtn = document.getElementById('existingTitleAssignBtn');
    if (existingCancelBtn) existingCancelBtn.onclick = () => hideModal('existingTitleModal');
    if (existingAssignBtn) existingAssignBtn.onclick = confirmExistingTitleAssign;

    document.addEventListener('click', (event) => {
        if (!titlePresetsState.selectedTitle) {
            return;
        }
        if (event.target.closest('#title-presets-list')) {
            return;
        }
        if (event.target.closest('.title-presets-actions')) {
            return;
        }
        if (event.target.closest('.modal, #modal-overlay')) {
            return;
        }
        clearTitlePresetSelection();
    });

    loadTitlePresets();
}

// --- Info tab console ---------------------------------------------------------

let consoleEventSource = null;
let consoleLatestId = 0;
let consoleStickToBottom = true;

function isConsoleScrolledToBottom(output) {
    if (!output) {
        return true;
    }
    return output.scrollHeight - output.scrollTop - output.clientHeight <= 1;
}

function scrollConsoleToBottom(output) {
    if (!output) {
        return;
    }
    output.scrollTop = output.scrollHeight;
}

function updateConsoleStickToBottom(output) {
    consoleStickToBottom = isConsoleScrolledToBottom(output);
}

function appendConsoleLines(lines) {
    const output = document.getElementById('infoConsoleOutput');
    if (!output || !lines.length) {
        return;
    }

    output.textContent += `${lines.map(entry => entry.text).join('\n')}\n`;

    if (consoleStickToBottom) {
        scrollConsoleToBottom(output);
    }

    const lastEntry = lines[lines.length - 1];
    if (lastEntry?.id) {
        consoleLatestId = Math.max(consoleLatestId, lastEntry.id);
    }
}

function startConsoleLogStream() {
    if (consoleEventSource) {
        return;
    }

    fetch(`/api/console/logs?since=${consoleLatestId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && Array.isArray(data.logs)) {
                appendConsoleLines(data.logs);
                if (data.latest_id) {
                    consoleLatestId = data.latest_id;
                }
            }

            consoleEventSource = new EventSource(`/api/console/stream?since=${consoleLatestId}`);
            consoleEventSource.onmessage = (event) => {
                try {
                    appendConsoleLines([JSON.parse(event.data)]);
                } catch (error) {
                }
            };
            consoleEventSource.onerror = () => {
            };
        })
        .catch(() => {});
}

// --- App updates (GitHub Releases) ------------------------------------------

const updateState = {
    current: window.CATSWITCH_VERSION || '',
    latest: null,
    updateAvailable: false,
    downloadUrl: null,
    notes: null,
    error: null,
    lastChecked: null,
    channelConfigured: true,
    installing: false,
};

function formatRelativeTimeAgo(date) {
    const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) {
        return 'just now';
    }

    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) {
        return minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;
    }

    const hours = Math.floor(minutes / 60);
    if (hours < 24) {
        return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
    }

    const days = Math.floor(hours / 24);
    if (days < 30) {
        return days === 1 ? '1 day ago' : `${days} days ago`;
    }

    const months = Math.floor(days / 30);
    if (months < 12) {
        return months === 1 ? '1 month ago' : `${months} months ago`;
    }

    const years = Math.floor(days / 365);
    return years === 1 ? '1 year ago' : `${years} years ago`;
}

function formatLastCheckedLabel(iso) {
    if (!iso) {
        return 'Last checked: never';
    }
    try {
        const date = new Date(iso);
        if (Number.isNaN(date.getTime())) {
            return 'Last checked: never';
        }
        return `Last checked: ${formatRelativeTimeAgo(date)}`;
    } catch (error) {
        return 'Last checked: never';
    }
}

function applyUpdateCheckPayload(data) {
    if (!data) {
        return;
    }
    updateState.current = data.current || updateState.current;
    updateState.latest = data.latest || null;
    updateState.updateAvailable = Boolean(data.update_available);
    // Install requires a SHA256 digest (GitHub asset digest or release notes)
    updateState.downloadUrl = (data.download_url && data.sha256) ? data.download_url : null;
    updateState.notes = data.notes || null;
    updateState.error = data.error || null;
    updateState.lastChecked = data.checked_at || data.last_checked || updateState.lastChecked;
    if (data.channel_configured !== undefined) {
        updateState.channelConfigured = Boolean(data.channel_configured);
    }
    refreshUpdateUiFromState();
}

function syncUpdateActionButton() {
    const actionBtn = document.getElementById('infoUpdateActionBtn');
    if (!actionBtn) {
        return;
    }

    const canInstall = Boolean(
        updateState.updateAvailable && updateState.downloadUrl && !updateState.installing
    );

    if (canInstall) {
        actionBtn.textContent = 'Update now';
        actionBtn.classList.remove('btn-secondary');
        actionBtn.classList.add('btn-primary');
        actionBtn.disabled = false;
        return;
    }

    actionBtn.textContent = updateState.installing ? 'Updating…' : 'Search for updates';
    actionBtn.classList.remove('btn-primary');
    actionBtn.classList.add('btn-secondary');
    actionBtn.disabled = Boolean(updateState.installing);
}

function refreshUpdateUiFromState() {
    const lastCheckedEl = document.getElementById('infoLastChecked');
    const statusEl = document.getElementById('infoUpdateStatus');
    const sidebarBtn = document.getElementById('sidebarUpdateBtn');

    if (lastCheckedEl) {
        lastCheckedEl.textContent = formatLastCheckedLabel(updateState.lastChecked);
    }

    if (sidebarBtn) {
        sidebarBtn.classList.toggle('hidden', !updateState.updateAvailable);
    }

    syncUpdateActionButton();

    if (!statusEl) {
        return;
    }

    statusEl.hidden = false;
    statusEl.classList.toggle('has-update', updateState.updateAvailable);

    if (updateState.installing) {
        statusEl.textContent = 'Downloading update… the app will close and restart.';
        return;
    }

    if (updateState.updateAvailable && updateState.latest) {
        let text = `Update available: v${updateState.latest}`;
        if (updateState.error) {
            text += ` — ${updateState.error}`;
        }
        statusEl.textContent = text;
        return;
    }

    if (!updateState.channelConfigured) {
        statusEl.textContent = 'Update channel is not configured yet.';
        return;
    }
    if (updateState.error && !updateState.latest) {
        statusEl.textContent = updateState.error;
        return;
    }
    if (updateState.lastChecked) {
        statusEl.textContent = updateState.latest
            ? `You're up to date (v${updateState.current || updateState.latest}).`
            : 'No update available.';
        return;
    }
    statusEl.hidden = true;
}

async function checkForAppUpdates({ silent = false, startup = false } = {}) {
    const actionBtn = document.getElementById('infoUpdateActionBtn');
    if (actionBtn && !silent) {
        actionBtn.disabled = true;
    }
    try {
        const response = await fetch('/api/updates/check', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ force: !startup }),
        });
        const data = await response.json();
        applyUpdateCheckPayload(data);
        if (!silent && !data.success && data.error && !data.update_available) {
            const statusEl = document.getElementById('infoUpdateStatus');
            if (statusEl) {
                statusEl.hidden = false;
                statusEl.textContent = data.error;
            }
        }
        return data;
    } catch (error) {
        if (!silent) {
            const statusEl = document.getElementById('infoUpdateStatus');
            if (statusEl) {
                statusEl.hidden = false;
                statusEl.textContent = 'Could not check for updates.';
            }
        }
        return null;
    } finally {
        if (actionBtn && !silent) {
            syncUpdateActionButton();
        }
    }
}

async function installAppUpdate() {
    if (updateState.installing || !updateState.downloadUrl) {
        return;
    }
    const actionBtn = document.getElementById('infoUpdateActionBtn');
    updateState.installing = true;
    refreshUpdateUiFromState();
    if (actionBtn) {
        actionBtn.disabled = true;
    }
    try {
        const response = await fetch('/api/updates/install', { method: 'POST' });
        const data = await response.json();
        if (!data.success) {
            updateState.installing = false;
            const statusEl = document.getElementById('infoUpdateStatus');
            if (statusEl) {
                statusEl.hidden = false;
                statusEl.textContent = data.error || 'Failed to start update.';
            }
            refreshUpdateUiFromState();
            return;
        }
        // App will exit shortly; keep installing state visible
    } catch (error) {
        updateState.installing = false;
        const statusEl = document.getElementById('infoUpdateStatus');
        if (statusEl) {
            statusEl.hidden = false;
            statusEl.textContent = 'Failed to start update.';
        }
        refreshUpdateUiFromState();
    }
}

async function openLegalFile(fileKey) {
    try {
        const response = await fetch('/api/open-legal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file: fileKey }),
        });
        const data = await response.json();
        if (!data.success) {
            showToast(data.error || 'Could not open file');
        }
    } catch (error) {
        showToast('Could not open file');
    }
}

function setupInfoLegalLinks() {
    document.querySelectorAll('[data-legal-file]').forEach((el) => {
        el.addEventListener('click', () => {
            openLegalFile(el.getAttribute('data-legal-file'));
        });
    });
}

function setupUpdates() {
    const actionBtn = document.getElementById('infoUpdateActionBtn');
    const sidebarBtn = document.getElementById('sidebarUpdateBtn');

    if (actionBtn) {
        actionBtn.addEventListener('click', () => {
            if (updateState.updateAvailable && updateState.downloadUrl && !updateState.installing) {
                installAppUpdate();
                return;
            }
            checkForAppUpdates({ silent: false });
        });
    }
    if (sidebarBtn) {
        sidebarBtn.addEventListener('click', () => {
            switchTab('info');
            const statusEl = document.getElementById('infoUpdateStatus');
            if (statusEl) {
                statusEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        });
    }

    setupInfoLegalLinks();

    // Load cached status, then optionally refresh in the background (throttled server-side via last_checked)
    fetch('/api/updates/status')
        .then((response) => response.json())
        .then((data) => {
            applyUpdateCheckPayload(data);
            if (data.should_check) {
                checkForAppUpdates({ silent: true, startup: true });
            }
        })
        .catch(() => {
            checkForAppUpdates({ silent: true, startup: true });
        });
}

function setupInfoConsole() {
    const layout = document.getElementById('infoTabLayout');
    const toggle = document.getElementById('infoConsoleToggle');
    const view = document.getElementById('infoConsoleView');
    const output = document.getElementById('infoConsoleOutput');
    const icon = toggle?.querySelector('.info-console-toggle-icon');

    if (!layout || !toggle || !view || !output) {
        return;
    }

    toggle.addEventListener('click', () => {
        const isOpen = layout.classList.toggle('console-open');
        toggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        view.hidden = !isOpen;

        if (icon) {
            icon.classList.toggle('icon-chevron-up', !isOpen);
            icon.classList.toggle('icon-chevron-down', isOpen);
        }

        if (isOpen && consoleStickToBottom) {
            scrollConsoleToBottom(output);
        }
    });

    output.addEventListener('scroll', () => {
        updateConsoleStickToBottom(output);
    }, { passive: true });

    output.addEventListener('keydown', (event) => {
        const key = event.key.toLowerCase();
        const withModifier = event.ctrlKey || event.metaKey;
        if (withModifier && (key === 'c' || key === 'a' || key === 'insert')) {
            return;
        }
        if (key === 'arrowup' || key === 'arrowdown' || key === 'pageup' || key === 'pagedown'
            || key === 'home' || key === 'end') {
            return;
        }
        event.preventDefault();
    });

    output.addEventListener('beforeinput', (event) => {
        const inputType = event.inputType || '';
        if (inputType.startsWith('insert') || inputType === 'insertFromPaste') {
            event.preventDefault();
        }
    });

    output.addEventListener('paste', (event) => {
        event.preventDefault();
    });

    startConsoleLogStream();
}