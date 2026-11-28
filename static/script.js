/**
 * Mandala Coloring Page Generator - Frontend Script
 *
 * Handles:
 * - Parameter controls (rings, divisions, complexity, categories)
 * - Live preview generation
 * - Saved designs (open, save, delete) and per-user preferences, kept in Firestore
 *   (coloring-users/{email}) for a signed-in user and in localStorage otherwise
 * - Collapsible sidebar sections
 * - Zoom and print functionality
 */

// Shown in the preview while a design is generating: the gold gear from the logo, spinning (still
// when the visitor prefers reduced motion). The text is for screen readers only.
const GENERATING_LOADER_HTML =
    '<div class="loader generating-loader" role="status">' +
        '<svg class="generating-gear" viewBox="-50 -50 100 100" width="64" height="64" aria-hidden="true" focusable="false">' +
            '<defs><linearGradient id="mf-generating-gold" x1="0" y1="-48" x2="0" y2="48" gradientUnits="userSpaceOnUse">' +
                '<stop offset="0" stop-color="#f7c65e"/><stop offset="0.5" stop-color="#dd8f22"/><stop offset="1" stop-color="#a95f10"/>' +
            '</linearGradient></defs>' +
            '<g fill="url(#mf-generating-gold)">' +
                '<path fill-rule="evenodd" d="M0,-38 A38,38 0 1 1 0,38 A38,38 0 1 1 0,-38Z M0,-22 A22,22 0 1 0 0,22 A22,22 0 1 0 0,-22Z"/>' +
                '<rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(0)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(30)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(60)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(90)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(120)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(150)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(180)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(210)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(240)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(270)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(300)"/><rect x="-7" y="-47" width="14" height="14" rx="2" transform="rotate(330)"/>' +
            '</g>' +
        '</svg>' +
        '<span class="visually-hidden">Generating...</span>' +
    '</div>';

// =============================================================================
// USER STORE: saved designs and preferences
// =============================================================================
//
// A signed-in visitor's saved designs and preferences live in Firestore, so they follow the account
// from browser to browser:
//
//     coloring-users/{email}                 { preferences: { theme, expandedSections }, updatedAt }
//     coloring-users/{email}/designs/{id}    { id, thumbnail, params, ring_seeds, timestamp, svg? }
//
// preferences is an open map: add new settings to it as they come along. firestore.rules in
// husted-dot-dev lets only that user, while on coloring-allowed-users, read and write their own
// document. With no signed-in user (local development), no Firestore SDK on the page, or Firestore
// refusing access, the store falls back to this browser's localStorage, which is where saved designs
// lived before. The first time an account connects, designs saved in this browser are copied into it.
function createUserStore() {
    const LOCAL_GALLERY_KEY = 'mandalaGallery';
    const LOCAL_PREFS_KEY = 'mandalaforge-prefs';
    const LOCAL_MIGRATED_PREFIX = 'mandalaforge-gallery-migrated:';
    // localStorage holds about 5 MB per site, so the browser copy keeps only the newest designs.
    const LOCAL_GALLERY_LIMIT = 12;
    const USERS_COLLECTION = 'coloring-users';
    const AUTH_WAIT_MS = 8000;
    const PREFS_WRITE_DELAY_MS = 400;

    let mode = 'local';
    let userDoc = null;
    let userEmail = null;
    let designs = [];
    let prefs = {};
    let prefsTimer = null;
    let connectPromise = null;

    const readLocalJson = (key, fallback) => {
        try {
            const raw = window.localStorage.getItem(key);
            return raw ? JSON.parse(raw) : fallback;
        } catch (error) {
            console.warn('LOGGING: [store] could not read', key, 'from localStorage', error);
            return fallback;
        }
    };

    const writeLocal = (key, value) => {
        try {
            window.localStorage.setItem(key, value);
            return true;
        } catch (error) {
            console.warn('LOGGING: [store] could not write', key, 'to localStorage', error);
            return false;
        }
    };

    const newestFirst = (a, b) => String(b.timestamp || '').localeCompare(String(a.timestamp || ''));

    // Write the browser's gallery, dropping the oldest entries if storage is full.
    const persistLocalGallery = () => {
        let items = designs.slice(0, LOCAL_GALLERY_LIMIT);
        while (items.length) {
            if (writeLocal(LOCAL_GALLERY_KEY, JSON.stringify(items))) {
                designs = items;
                return;
            }
            items = items.slice(0, -1);
        }
        writeLocal(LOCAL_GALLERY_KEY, '[]');
        designs = [];
    };

    prefs = readLocalJson(LOCAL_PREFS_KEY, {}) || {};
    designs = readLocalJson(LOCAL_GALLERY_KEY, []) || [];

    // Resolve with the signed-in user, or null when there is none or Firebase is not on the page.
    const waitForUser = () => new Promise((resolve) => {
        const fb = window.firebase;
        if (!fb || typeof fb.auth !== 'function' || typeof fb.firestore !== 'function') {
            console.log('LOGGING: [store] Firebase Auth or Firestore not on this page, using this browser only');
            resolve(null);
            return;
        }
        let auth;
        try {
            auth = fb.auth();
        } catch (error) {
            console.warn('LOGGING: [store] Firebase is not initialised, using this browser only', error);
            resolve(null);
            return;
        }
        if (auth.currentUser) {
            resolve(auth.currentUser);
            return;
        }
        let settled = false;
        let unsubscribe = null;
        const finish = (user) => {
            if (settled) return;
            settled = true;
            if (unsubscribe) unsubscribe();
            resolve(user);
        };
        setTimeout(() => {
            console.warn('LOGGING: [store] sign-in state did not arrive in time, using this browser only');
            finish(null);
        }, AUTH_WAIT_MS);
        unsubscribe = auth.onAuthStateChanged(user => finish(user || null));
        if (settled && unsubscribe) unsubscribe();
    });

    const connect = () => {
        if (connectPromise) return connectPromise;
        connectPromise = (async () => {
            const user = await waitForUser();
            if (!user || !user.email) {
                console.log('LOGGING: [store] no signed-in account, saved designs and preferences stay in this browser');
                return mode;
            }
            try {
                const doc = window.firebase.firestore().collection(USERS_COLLECTION).doc(user.email);
                const snapshot = await doc.get();
                userDoc = doc;
                userEmail = user.email;
                mode = 'firestore';
                const data = snapshot.exists ? snapshot.data() : {};
                if (data && data.preferences && typeof data.preferences === 'object') {
                    prefs = { ...prefs, ...data.preferences };
                    writeLocal(LOCAL_PREFS_KEY, JSON.stringify(prefs));
                }
                console.log('LOGGING: [store] using account storage for', user.email, snapshot.exists ? '(existing)' : '(new)');
            } catch (error) {
                console.error('LOGGING: [store] account storage unavailable, using this browser only', error);
                mode = 'local';
                userDoc = null;
            }
            return mode;
        })();
        return connectPromise;
    };

    // Copy designs saved in this browser into the account, once per account per browser.
    const migrateLocalDesigns = async (accountDesigns) => {
        const flagKey = LOCAL_MIGRATED_PREFIX + userEmail;
        if (readLocalJson(flagKey, false)) return accountDesigns;
        const localDesigns = (readLocalJson(LOCAL_GALLERY_KEY, []) || []).filter(item => item && item.id);
        const known = new Set(accountDesigns.map(item => String(item.id)));
        const toCopy = localDesigns.filter(item => !known.has(String(item.id)));
        console.log(`LOGGING: [store] copying ${toCopy.length} design(s) saved in this browser into the account`);
        for (const item of toCopy) {
            await userDoc.collection('designs').doc(String(item.id)).set(item);
        }
        writeLocal(flagKey, 'true');
        return accountDesigns.concat(toCopy).sort(newestFirst);
    };

    const loadDesigns = async () => {
        if (mode !== 'firestore') {
            designs = (readLocalJson(LOCAL_GALLERY_KEY, []) || []).sort(newestFirst);
            console.log(`LOGGING: [store] loaded ${designs.length} saved design(s) from this browser`);
            return designs.slice();
        }
        const snapshot = await userDoc.collection('designs').get();
        let loaded = snapshot.docs.map(doc => ({ ...doc.data(), id: doc.data().id || doc.id })).sort(newestFirst);
        try {
            loaded = await migrateLocalDesigns(loaded);
        } catch (error) {
            console.error('LOGGING: [store] could not copy this browser\'s designs into the account', error);
        }
        designs = loaded;
        console.log(`LOGGING: [store] loaded ${designs.length} saved design(s) from the account`);
        return designs.slice();
    };

    const addDesign = async (item) => {
        if (mode === 'firestore') {
            await userDoc.collection('designs').doc(String(item.id)).set(item);
            designs = [item].concat(designs);
            console.log('LOGGING: [store] saved design', item.id, 'to the account');
        } else {
            designs = [item].concat(designs);
            persistLocalGallery();
            console.log('LOGGING: [store] saved design', item.id, 'in this browser');
        }
        return designs.slice();
    };

    const deleteDesign = async (id) => {
        if (mode === 'firestore') {
            await userDoc.collection('designs').doc(String(id)).delete();
            designs = designs.filter(item => String(item.id) !== String(id));
            console.log('LOGGING: [store] deleted design', id, 'from the account');
        } else {
            designs = designs.filter(item => String(item.id) !== String(id));
            persistLocalGallery();
            console.log('LOGGING: [store] deleted design', id, 'from this browser');
        }
        return designs.slice();
    };

    const flushPrefs = () => {
        prefsTimer = null;
        if (mode !== 'firestore') return;
        userDoc.set({
            preferences: prefs,
            updatedAt: window.firebase.firestore.FieldValue.serverTimestamp()
        }, { merge: true })
            .then(() => console.log('LOGGING: [store] preferences saved to the account', prefs))
            .catch(error => console.error('LOGGING: [store] could not save preferences to the account', error));
    };

    // Merge a change into the preferences. This browser's copy is written at once; the account copy
    // shortly after, so a burst of changes (several sections toggled) is one write.
    const savePrefs = (patch) => {
        prefs = { ...prefs, ...patch };
        writeLocal(LOCAL_PREFS_KEY, JSON.stringify(prefs));
        if (mode !== 'firestore') {
            console.log('LOGGING: [store] preferences saved in this browser', prefs);
            return;
        }
        if (prefsTimer) clearTimeout(prefsTimer);
        prefsTimer = setTimeout(flushPrefs, PREFS_WRITE_DELAY_MS);
    };

    return {
        connect,
        loadDesigns,
        addDesign,
        deleteDesign,
        savePrefs,
        prefs: () => ({ ...prefs }),
        designs: () => designs.slice(),
        mode: () => mode
    };
}

function initColoringApp() {
    // Buttons
    const generateBtn = document.getElementById('generate-btn');
    const randomizeBtn = document.getElementById('randomize-btn');
    const saveBtn = document.getElementById('save-btn');
    const regenerateRingBtn = document.getElementById('regenerate-ring-btn');
    const printBtn = document.getElementById('print-btn');

    // Sliders and inputs
    const numRingsSlider = document.getElementById('num-rings');
    const numDivisionsSlider = document.getElementById('num-divisions');
    const complexitySlider = document.getElementById('complexity');
    const minPatternSizeSlider = document.getElementById('min-pattern-size');
    const seedInput = document.getElementById('seed');
    const includeParamsCheck = document.getElementById('include-params-check');
    const varyDivisionsCheck = document.getElementById('vary-divisions');
    const maxRegionCapCheck = document.getElementById('max-region-cap');

    // Category checkboxes
    const catBotanical = document.getElementById('cat-botanical');
    const catGeometric = document.getElementById('cat-geometric');
    const catCeltic = document.getElementById('cat-celtic');
    const catArtDeco = document.getElementById('cat-art-deco');
    const catAbstract = document.getElementById('cat-abstract');
    const categoryWarning = document.getElementById('category-warning');

    // Value displays
    const numRingsValue = document.getElementById('num-rings-value');
    const numDivisionsValue = document.getElementById('num-divisions-value');
    const complexityValue = document.getElementById('complexity-value');
    const minPatternSizeValue = document.getElementById('min-pattern-size-value');
    const numRingsPending = document.getElementById('num-rings-pending');
    const numDivisionsPending = document.getElementById('num-divisions-pending');
    const complexityPending = document.getElementById('complexity-pending');
    const minPatternSizePending = document.getElementById('min-pattern-size-pending');

    // Preview elements
    const paramsText = document.getElementById('params-text');
    const galleryGrid = document.getElementById('gallery-grid');
    const ringSelector = document.getElementById('ring-selector');
    const mandalaDesign = document.getElementById('mandala-design');
    const paperSheet = document.getElementById('paper-sheet');
    const pagePreview = document.getElementById('page-preview');
    const printRoot = document.getElementById('print-root');
    const printDesign = document.getElementById('print-design');
    const printParamsPage = document.getElementById('print-params-page');

    // Zoom controls
    const zoomInBtn = document.getElementById('zoom-in');
    const zoomOutBtn = document.getElementById('zoom-out');
    const fitToPageBtn = document.getElementById('fit-to-page');
    const zoomLevelSpan = document.getElementById('zoom-level');

    // Saved designs and preferences (see createUserStore below)
    const userStore = createUserStore();

    // State
    let activeSeed = null;
    let galleryItems = [];
    let currentZoom = 1;
    let isDragging = false;
    let dragStart = { x: 0, y: 0 };
    let sheetPosition = { x: 0, y: 0 };
    let selectedRingIndex = null;
    let currentDesignParams = null;

    // ==========================================================================
    // CATEGORY HELPERS
    // ==========================================================================

    const getSelectedCategories = () => {
        const categories = [];
        if (catBotanical.checked) categories.push('botanical');
        if (catGeometric.checked) categories.push('geometric');
        if (catCeltic.checked) categories.push('celtic');
        if (catArtDeco.checked) categories.push('art_deco');
        if (catAbstract.checked) categories.push('abstract');
        return categories;
    };

    // Categories with registered motifs. Celtic, art deco and abstract have none yet, so their
    // checkboxes are disabled; the API still accepts them and builds safe bands.
    const AVAILABLE_CATEGORIES = ['botanical', 'geometric'];

    // Drop categories the UI cannot offer, falling back to botanical when nothing remains.
    const availableCategories = (categories) => {
        const kept = (categories || []).filter(category => AVAILABLE_CATEGORIES.includes(category));
        return kept.length ? kept : ['botanical'];
    };

    const validateCategories = () => {
        const categories = getSelectedCategories();
        if (categories.length === 0) {
            categoryWarning.style.display = 'block';
            return false;
        }
        categoryWarning.style.display = 'none';
        return true;
    };

    const createRandomSeed = () => Math.floor(Math.random() * 1000000).toString();

    const buildGenerationPayload = (seedForGeneration) => ({
        seed: seedForGeneration,
        num_rings: parseInt(numRingsSlider.value),
        num_divisions: parseInt(numDivisionsSlider.value),
        complexity: parseFloat(complexitySlider.value),
        min_pattern_size: parseFloat(minPatternSizeSlider.value),
        categories: getSelectedCategories(),
        vary_divisions: varyDivisionsCheck.checked,
        max_region_cap: maxRegionCapCheck.checked
    });

    const getCleanCurrentSvgMarkup = () => {
        const currentSvg = mandalaDesign.querySelector('svg');
        if (!currentSvg) return '';

        const svgClone = currentSvg.cloneNode(true);
        svgClone.querySelectorAll('.selected-ring').forEach(node => {
            node.classList.remove('selected-ring');
        });
        return svgClone.outerHTML;
    };

    const resetRingSelection = () => {
        selectedRingIndex = null;
        mandalaDesign.querySelectorAll('.selected-ring').forEach(node => {
            node.classList.remove('selected-ring');
        });
        ringSelector.querySelectorAll('.ring-select-btn').forEach(button => {
            button.classList.remove('active');
            button.setAttribute('aria-pressed', 'false');
        });
        regenerateRingBtn.disabled = true;
        regenerateRingBtn.textContent = 'Regenerate Ring';
    };

    const updateRingSelectorState = () => {
        ringSelector.querySelectorAll('.ring-select-btn').forEach(button => {
            const isSelected = parseInt(button.dataset.ringIndex, 10) === selectedRingIndex;
            button.classList.toggle('active', isSelected);
            button.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
        });
    };

    const selectRingByIndex = (ringIndex) => {
        mandalaDesign.querySelectorAll('.selected-ring').forEach(node => {
            node.classList.remove('selected-ring');
        });

        const ringGroup = mandalaDesign.querySelector(`#mandala > g#ring-${ringIndex}`);
        if (ringGroup) {
            ringGroup.classList.add('selectable-ring', 'selected-ring');
        }

        selectedRingIndex = ringIndex;
        updateRingSelectorState();
        regenerateRingBtn.disabled = false;
        regenerateRingBtn.textContent = `Regenerate Ring ${selectedRingIndex + 1}`;
    };

    const selectRing = (ringGroup) => {
        selectRingByIndex(parseInt(ringGroup.id.replace('ring-', ''), 10));
    };

    const designToast = document.getElementById('design-toast');
    let designToastTimer = null;

    // Base motif of a sequence entry: the centre recipe if present, else the divider.
    const entryRecipe = (entry) => (entry && (entry.centre || entry.divider)) || null;

    // "petal+diamond": the base motif followed by each slot child down the chain.
    const entryChainSummary = (entry) => {
        const names = [];
        let recipe = entryRecipe(entry);
        while (recipe) {
            names.push(recipe.motif);
            recipe = recipe.slot_child;
        }
        return names.join('+');
    };

    // "petal/scallop": the ring's sequence entries joined by '/'.
    const ringEntriesSummary = (ring) => (ring.sequence || []).map(entryChainSummary).join('/');

    // Every value needed to reproduce the design on screen, ring regenerations and motif choices
    // included. It is no longer shown on the page; it goes to the console so a report of "this one
    // looks wrong" can still be turned back into a test case.
    const logReproduction = (payload, data) => {
        const rings = ((data.plan && data.plan.rings) || []).map((ring, i) => (
            `R${i + 1}=${ring.divisions}:${ringEntriesSummary(ring)}`
        ));
        const parts = [
            `seed=${data.used_seed}`,
            `rings=${payload.num_rings}`,
            `divisions=${payload.num_divisions}`,
            `minSize=${payload.min_pattern_size}`,
            `complexity=${payload.complexity}`,
            `categories=${(payload.categories || []).join('+')}`,
        ];
        if (payload.vary_divisions) parts.push('vary=true');
        if (payload.max_region_cap) parts.push('cap=true');
        // Base symmetry: every ring's division count is a multiple of it.
        if (data.plan && data.plan.base_symmetry) parts.push(`B=${data.plan.base_symmetry}`);
        // Rings regenerated on their own: "<ring index>:<seed>", the keys /generate takes as ring_seeds.
        const ringSeeds = Object.entries(data.ring_seeds || {})
            .sort(([a], [b]) => parseInt(a, 10) - parseInt(b, 10))
            .map(([index, seed]) => `${index}:${seed}`);
        if (ringSeeds.length) parts.push(`ring_seeds=${ringSeeds.join(',')}`);
        if (data.validation) {
            parts.push(`valid=${data.validation.is_valid}`);
            if (!data.validation.is_valid) parts.push(`issues=${data.validation.issue_count}`);
        }
        console.log('LOGGING: [design] reproduction:', parts.concat(rings).join('  '));
    };

    let currentPlan = null;
    let currentRingSeeds = {};

    // The QA pipeline decides whether a design is actually colourable. Its verdict pops up over the
    // preview for a moment once a design finishes: briefly when it passed, a little longer when it
    // found problems, so there is time to read the count.
    const TOAST_VALID_MS = 1600;
    const TOAST_INVALID_MS = 4500;

    const showDesignToast = (validation) => {
        if (!designToast) return;
        if (designToastTimer) {
            clearTimeout(designToastTimer);
            designToastTimer = null;
        }
        if (!validation) {
            designToast.hidden = true;
            designToast.classList.remove('is-showing');
            return;
        }
        designToast.classList.toggle('is-valid', validation.is_valid);
        designToast.classList.toggle('is-invalid', !validation.is_valid);
        designToast.textContent = validation.is_valid
            ? 'Checked: all lines connect, every space is colourable'
            : `Check found ${validation.issue_count} issue${validation.issue_count === 1 ? '' : 's'}`;
        designToast.title = validation.is_valid
            ? ''
            : (validation.issues || []).slice(0, 8).join('\n');
        designToast.hidden = false;
        // Restart the fade-in when a toast is already up
        designToast.classList.remove('is-showing');
        void designToast.offsetWidth;
        designToast.classList.add('is-showing');
        console.log('LOGGING: [design] check result toast:', designToast.textContent);

        designToastTimer = setTimeout(() => {
            designToast.classList.remove('is-showing');
            designToastTimer = setTimeout(() => {
                designToast.hidden = true;
                designToastTimer = null;
            }, 250);
        }, validation.is_valid ? TOAST_VALID_MS : TOAST_INVALID_MS);
    };

    const renderRingSelector = () => {
        ringSelector.innerHTML = '';
        const svg = mandalaDesign.querySelector('svg');
        if (!svg) {
            ringSelector.hidden = true;
            return;
        }

        const rings = Array.from(svg.querySelectorAll('#mandala > g[id^="ring-"]'))
            .filter(ringGroup => /^ring-\d+$/.test(ringGroup.id))
            .map(ringGroup => parseInt(ringGroup.id.replace('ring-', ''), 10))
            .sort((a, b) => a - b);

        ringSelector.hidden = rings.length === 0;
        rings.forEach(ringIndex => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'ring-select-btn';
            button.dataset.ringIndex = ringIndex;
            const planRing = currentPlan && currentPlan.rings ? currentPlan.rings[ringIndex] : null;
            const divisionsSuffix = planRing && planRing.divisions ? ` \u00b7 ${planRing.divisions}` : '';
            button.textContent = `Ring ${ringIndex + 1}${divisionsSuffix}`;
            const baseRecipe = planRing ? entryRecipe((planRing.sequence || [])[0]) : null;
            if (baseRecipe && baseRecipe.motif) {
                // The motif name is the most useful thing to know before re-rolling a ring
                const pretty = baseRecipe.motif.replace(/_/g, ' ');
                // How the ring connects inward: side, overflow or stem
                const mode = planRing.contact_mode ? ` \u00b7 ${planRing.contact_mode}` : '';
                button.title = `Ring ${ringIndex + 1}: ${pretty}${mode}`;
                const tag = document.createElement('span');
                tag.className = 'ring-pattern-name';
                tag.textContent = `${pretty}${mode}`;
                button.appendChild(tag);
            }
            button.setAttribute('aria-pressed', 'false');
            button.addEventListener('click', () => selectRingByIndex(ringIndex));
            ringSelector.appendChild(button);
        });
    };

    const prepareRingSelection = () => {
        resetRingSelection();
        const svg = mandalaDesign.querySelector('svg');
        renderRingSelector();
        if (!svg) return;

        svg.querySelectorAll('#mandala > g[id^="ring-"]').forEach(ringGroup => {
            if (/^ring-\d+$/.test(ringGroup.id)) {
                ringGroup.classList.add('selectable-ring');
            }
        });
    };

    mandalaDesign.addEventListener('click', (event) => {
        const ringGroup = event.target.closest('g[id^="ring-"]');
        if (!ringGroup || !mandalaDesign.contains(ringGroup)) return;
        if (!/^ring-\d+$/.test(ringGroup.id)) return;
        if (!ringGroup.parentElement || ringGroup.parentElement.id !== 'mandala') return;

        selectRing(ringGroup);
    });

    const sliderControls = [
        {
            input: numRingsSlider,
            valueDisplay: numRingsValue,
            statusDisplay: numRingsPending,
            key: 'num_rings',
            read: () => parseInt(numRingsSlider.value, 10),
            format: value => value.toString()
        },
        {
            input: numDivisionsSlider,
            valueDisplay: numDivisionsValue,
            statusDisplay: numDivisionsPending,
            key: 'num_divisions',
            read: () => parseInt(numDivisionsSlider.value, 10),
            format: value => value.toString()
        },
        {
            input: minPatternSizeSlider,
            valueDisplay: minPatternSizeValue,
            statusDisplay: minPatternSizePending,
            key: 'min_pattern_size',
            read: () => parseFloat(minPatternSizeSlider.value),
            format: value => `${value}px`
        },
        {
            input: complexitySlider,
            valueDisplay: complexityValue,
            statusDisplay: complexityPending,
            key: 'complexity',
            read: () => parseFloat(complexitySlider.value),
            format: value => value.toFixed(1)
        }
    ];

    const syncPendingParameterIndicators = () => {
        sliderControls.forEach(control => {
            const controlGroup = control.input.closest('.control-group');
            if (!controlGroup) return;

            const hasGeneratedValue = currentDesignParams && currentDesignParams[control.key] !== undefined;
            const currentValue = control.read();
            const generatedValue = hasGeneratedValue ? parseFloat(currentDesignParams[control.key]) : currentValue;
            const isPending = hasGeneratedValue && currentValue !== generatedValue;

            controlGroup.classList.toggle('pending-value', isPending);
            control.valueDisplay.classList.toggle('pending-value-display', isPending);
            if (control.statusDisplay) {
                control.statusDisplay.hidden = !isPending;
            }
            control.input.setAttribute(
                'title',
                isPending
                    ? `Current design used ${control.format(generatedValue)}. Generate to apply ${control.format(currentValue)}.`
                    : ''
            );
        });
    };

    const updateSliderDisplay = (control) => {
        control.valueDisplay.textContent = control.format(control.read());
        syncPendingParameterIndicators();
    };

    // ==========================================================================
    // INPUT EVENT HANDLERS
    // ==========================================================================

    // Sliders
    numRingsSlider.addEventListener('input', () => {
        updateSliderDisplay(sliderControls[0]);
    });

    numDivisionsSlider.addEventListener('input', () => {
        updateSliderDisplay(sliderControls[1]);
    });

    complexitySlider.addEventListener('input', () => {
        updateSliderDisplay(sliderControls[3]);
    });

    minPatternSizeSlider.addEventListener('input', () => {
        updateSliderDisplay(sliderControls[2]);
    });

    // Category checkboxes
    [catBotanical, catGeometric, catCeltic, catArtDeco, catAbstract].forEach(checkbox => {
        checkbox.addEventListener('change', () => {
            validateCategories();
        });
    });

    // ==========================================================================
    // PRINTED PARAMETERS
    // ==========================================================================

    const CATEGORY_LABELS = {
        botanical: 'Botanical',
        geometric: 'Geometric',
        celtic: 'Celtic',
        art_deco: 'Art Deco',
        abstract: 'Abstract'
    };

    // The second print page: only the settings a person can enter in the sidebar, labelled as they
    // are there, so the design can be made again by typing them back in.
    const buildPrintableParams = (params) => {
        if (!params) return '';
        const yesNo = value => (value ? 'Yes' : 'No');
        const categories = (params.categories || []).map(category => CATEGORY_LABELS[category] || category);
        const lines = [
            `Seed: ${params.seed}`,
            `Rings: ${params.num_rings}`,
            `Divisions: ${params.num_divisions}`,
            `Vary divisions per ring: ${yesNo(params.vary_divisions)}`,
            `Limit large regions: ${yesNo(params.max_region_cap)}`,
            `Min Pattern Size: ${params.min_pattern_size}px`,
            `Detail Level: ${parseFloat(params.complexity).toFixed(1)}`,
            `Pattern Categories: ${categories.join(', ')}`
        ];
        return lines.join('\n');
    };

    // ==========================================================================
    // GENERATE MANDALA
    // ==========================================================================

    // restore: a saved design's {params, ringSeeds}. It is rebuilt from those exactly,
    // ring regenerations included, instead of from the controls.
    const generateMandala = async (restore = null) => {
        let payload;
        if (restore) {
            payload = { ...restore.params };
        } else {
            if (!validateCategories()) return;

            const userInputSeed = seedInput.value.trim();

            let seedForGeneration;
            if (userInputSeed) {
                seedForGeneration = userInputSeed;
            } else if (activeSeed) {
                seedForGeneration = activeSeed;
            } else {
                seedForGeneration = Math.floor(Math.random() * 1000000);
            }

            payload = buildGenerationPayload(seedForGeneration);
        }
        // A fresh design has no per-ring regenerations
        currentRingSeeds = {};
        const requestBody = restore ? { ...payload, ring_seeds: restore.ringSeeds || {} } : payload;

        console.log('Sending payload:', requestBody);
        resetRingSelection();
        mandalaDesign.innerHTML = GENERATING_LOADER_HTML;

        try {
            const response = await fetch('/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody),
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            mandalaDesign.innerHTML = data.svg;
            activeSeed = data.used_seed;
            currentDesignParams = { ...payload, seed: data.used_seed };
            currentPlan = data.plan || null;
            currentRingSeeds = data.ring_seeds || {};
            syncPendingParameterIndicators();
            prepareRingSelection();
            if (data.validation && !data.validation.is_valid) {
                console.warn('Mandala validation issues:', data.validation.issues);
            }
            showDesignToast(data.validation);
            logReproduction(payload, data);
            paramsText.textContent = buildPrintableParams(currentDesignParams);

        } catch (error) {
            console.error("Error generating mandala:", error);
            resetRingSelection();
            showDesignToast(null);
            mandalaDesign.innerHTML = `<div class="error">Failed to generate mandala: ${error.message}</div>`;
        }
    };

    const regenerateSelectedRing = async () => {
        if (selectedRingIndex === null || !currentDesignParams) return;
        if (!mandalaDesign.querySelector('svg')) return;

        const ringIndex = selectedRingIndex;
        const payload = {
            ...currentDesignParams,
            ring_index: ringIndex,
            ring_seed: Math.floor(Math.random() * 1000000),
            ring_seeds: currentRingSeeds
        };

        regenerateRingBtn.disabled = true;
        regenerateRingBtn.textContent = 'Regenerating...';

        try {
            const response = await fetch('/regenerate-ring', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            const data = await response.json();
            if (!response.ok || data.error) {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }

            // Rings reach into each other, so the server returns the whole document
            mandalaDesign.innerHTML = data.svg;
            currentRingSeeds = data.ring_seeds || {};
            currentPlan = data.plan || null;
            prepareRingSelection();
            selectRingByIndex(ringIndex);
            syncPendingParameterIndicators();

            if (data.validation && !data.validation.is_valid) {
                console.warn('Ring validation issues:', data.validation.issues);
            }
            showDesignToast(data.validation);
            logReproduction(currentDesignParams, { ...data, used_seed: activeSeed });
        } catch (error) {
            console.error('Error regenerating ring:', error);
            regenerateRingBtn.textContent = 'Regenerate Ring Failed';
            setTimeout(() => {
                regenerateRingBtn.textContent = selectedRingIndex === null ? 'Regenerate Ring' : `Regenerate Ring ${selectedRingIndex + 1}`;
                regenerateRingBtn.disabled = selectedRingIndex === null;
            }, 1500);
            return;
        }

        regenerateRingBtn.disabled = false;
        regenerateRingBtn.textContent = `Regenerate Ring ${selectedRingIndex + 1}`;
    };

    regenerateRingBtn.addEventListener('click', regenerateSelectedRing);

    // ==========================================================================
    // GENERATE AND RANDOMIZE BUTTONS
    // ==========================================================================

    generateBtn.addEventListener('click', () => {
        activeSeed = createRandomSeed();
        seedInput.value = activeSeed;
        generateMandala();
    });

    randomizeBtn.addEventListener('click', () => {
        console.log('Randomize: Randomizing parameters');

        // Randomize sliders
        numRingsSlider.value = Math.floor(Math.random() * 6) + 2; // 2-7
        numDivisionsSlider.value = (Math.floor(Math.random() * 10) + 3) * 2; // 6-24, even
        complexitySlider.value = (Math.random() * 0.8 + 0.2).toFixed(1); // 0.2-1.0
        minPatternSizeSlider.value = Math.floor(Math.random() * 30) + 10; // 10-40

        varyDivisionsCheck.checked = Math.random() < 0.5;
        // The region cap is a speed/quality choice, not a design parameter: Randomize leaves it as the user set it.

        // Update displays
        sliderControls.forEach(updateSliderDisplay);

        // Randomize the categories that have motifs (ensure at least one is checked)
        const availableCats = [catBotanical, catGeometric];
        availableCats.forEach(cat => cat.checked = Math.random() > 0.5);
        [catCeltic, catArtDeco, catAbstract].forEach(cat => cat.checked = false);

        // Ensure at least one category
        if (getSelectedCategories().length === 0) {
            availableCats[Math.floor(Math.random() * availableCats.length)].checked = true;
        }

        activeSeed = createRandomSeed();
        seedInput.value = activeSeed;
        generateMandala();
    });

    // ==========================================================================
    // GALLERY
    // ==========================================================================

    const THUMBNAIL_SIZE = 320;

    // A small JPEG of the whole design, drawn from the on-screen SVG. Resolves to a
    // data URL, or null if the browser cannot rasterise it.
    const createThumbnail = () => new Promise((resolve) => {
        const currentSvg = mandalaDesign.querySelector('svg');
        if (!currentSvg) {
            resolve(null);
            return;
        }

        const svgClone = currentSvg.cloneNode(true);
        svgClone.querySelectorAll('.selected-ring').forEach(node => {
            node.classList.remove('selected-ring');
        });
        svgClone.removeAttribute('style');
        svgClone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        // An <img> needs an intrinsic size; fall back to the viewBox when width/height are absent
        const viewBox = (svgClone.getAttribute('viewBox') || '').split(/[\s,]+/).map(parseFloat);
        let width = parseFloat(svgClone.getAttribute('width'));
        let height = parseFloat(svgClone.getAttribute('height'));
        if (!(width > 0 && height > 0)) {
            width = viewBox[2] > 0 ? viewBox[2] : THUMBNAIL_SIZE;
            height = viewBox[3] > 0 ? viewBox[3] : THUMBNAIL_SIZE;
            svgClone.setAttribute('width', width);
            svgClone.setAttribute('height', height);
        }

        const markup = new XMLSerializer().serializeToString(svgClone);
        const url = URL.createObjectURL(new Blob([markup], { type: 'image/svg+xml' }));
        const image = new Image();
        image.onload = () => {
            const canvas = document.createElement('canvas');
            canvas.width = THUMBNAIL_SIZE;
            canvas.height = THUMBNAIL_SIZE;
            const context = canvas.getContext('2d');
            // JPEG has no transparency, so paint the paper white first
            context.fillStyle = '#ffffff';
            context.fillRect(0, 0, THUMBNAIL_SIZE, THUMBNAIL_SIZE);
            const scale = Math.min(THUMBNAIL_SIZE / width, THUMBNAIL_SIZE / height);
            const drawWidth = width * scale;
            const drawHeight = height * scale;
            context.drawImage(image, (THUMBNAIL_SIZE - drawWidth) / 2, (THUMBNAIL_SIZE - drawHeight) / 2, drawWidth, drawHeight);
            URL.revokeObjectURL(url);
            resolve(canvas.toDataURL('image/jpeg', 0.85));
        };
        image.onerror = () => {
            URL.revokeObjectURL(url);
            resolve(null);
        };
        image.src = url;
    });

    // A saved design is its seed specs (params and ring_seeds) plus a JPEG thumbnail.
    // The design itself is regenerated from the specs when it is opened again.
    const saveToGallery = async (params, ringSeeds) => {
        const thumbnail = await createThumbnail();
        const item = {
            id: Date.now(),
            thumbnail: thumbnail,
            params: params,
            ring_seeds: { ...(ringSeeds || {}) },
            timestamp: new Date().toISOString()
        };
        // Without a thumbnail keep the SVG so the entry still has a preview
        if (!thumbnail) item.svg = getCleanCurrentSvgMarkup();

        galleryItems = await userStore.addDesign(item);
        renderGallery();
    };

    // Saved params in the shape /generate takes; older entries stored slider strings.
    const normaliseSavedParams = (params) => ({
        seed: params.seed,
        num_rings: parseInt(params.num_rings, 10),
        num_divisions: parseInt(params.num_divisions, 10),
        complexity: parseFloat(params.complexity),
        min_pattern_size: parseFloat(params.min_pattern_size),
        categories: availableCategories(params.categories),
        vary_divisions: !!params.vary_divisions,
        max_region_cap: !!params.max_region_cap
    });

    // Show a saved design's settings in the controls, so Generate and the pending
    // indicators start from the restored design.
    const applyParamsToControls = (params) => {
        numRingsSlider.value = params.num_rings;
        numDivisionsSlider.value = params.num_divisions;
        complexitySlider.value = params.complexity;
        minPatternSizeSlider.value = params.min_pattern_size;
        catBotanical.checked = params.categories.includes('botanical');
        catGeometric.checked = params.categories.includes('geometric');
        catCeltic.checked = params.categories.includes('celtic');
        catArtDeco.checked = params.categories.includes('art_deco');
        catAbstract.checked = params.categories.includes('abstract');
        varyDivisionsCheck.checked = params.vary_divisions;
        maxRegionCapCheck.checked = params.max_region_cap;
        seedInput.value = params.seed;
        validateCategories();
        sliderControls.forEach(control => {
            control.valueDisplay.textContent = control.format(control.read());
        });
    };

    const openSavedDesign = (item) => {
        if (!item.params || item.params.seed === undefined || item.params.seed === null) {
            // Nothing to regenerate from: show the stored picture as it was
            if (!item.svg) return;
            mandalaDesign.innerHTML = item.svg;
            currentPlan = item.plan || null;
            currentRingSeeds = { ...(item.ring_seeds || {}) };
            prepareRingSelection();
            return;
        }

        const params = normaliseSavedParams(item.params);
        applyParamsToControls(params);
        activeSeed = params.seed;
        generateMandala({ params, ringSeeds: item.ring_seeds || {} });
    };

    let galleryLoading = true;

    const renderGallery = () => {
        galleryGrid.innerHTML = '';

        if (galleryItems.length === 0) {
            const emptyMessage = document.createElement('div');
            emptyMessage.className = 'gallery-empty';
            emptyMessage.textContent = galleryLoading
                ? 'Loading saved designs...'
                : 'No saved designs yet. Click "Save Design" to add one!';
            galleryGrid.appendChild(emptyMessage);
            return;
        }

        galleryItems.forEach(item => {
            const galleryItem = document.createElement('div');
            galleryItem.className = 'gallery-item';
            galleryItem.tabIndex = 0;
            galleryItem.setAttribute('role', 'button');
            if (item.thumbnail) {
                const image = document.createElement('img');
                image.src = item.thumbnail;
                image.alt = '';
                galleryItem.appendChild(image);
            } else {
                // Entries saved before thumbnails existed carry the full SVG
                galleryItem.innerHTML = item.svg || '';
            }
            const savedAt = new Date(item.timestamp).toLocaleString();
            const seedNote = item.params ? `Seed ${item.params.seed}. ` : '';
            galleryItem.title = `${seedNote}Saved: ${savedAt}`;
            galleryItem.setAttribute('aria-label', `Open saved design${item.params ? `, seed ${item.params.seed}` : ''}, saved ${savedAt}`);
            galleryItem.addEventListener('click', () => openSavedDesign(item));
            galleryItem.addEventListener('keydown', (event) => {
                if (event.target !== galleryItem) return;
                if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    openSavedDesign(item);
                }
            });

            const deleteBtn = document.createElement('button');
            deleteBtn.type = 'button';
            deleteBtn.className = 'gallery-delete';
            deleteBtn.setAttribute('aria-label', 'Delete this saved design');
            deleteBtn.title = 'Delete this saved design';
            deleteBtn.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true" focusable="false">' +
                '<path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>';
            deleteBtn.addEventListener('click', (event) => {
                event.stopPropagation();
                confirmDeleteDesign(item);
            });
            deleteBtn.addEventListener('keydown', event => event.stopPropagation());
            galleryItem.appendChild(deleteBtn);

            galleryGrid.appendChild(galleryItem);
        });
    };

    // ==========================================================================
    // DELETE SAVED DESIGNS
    // ==========================================================================

    const deleteDialog = document.getElementById('delete-design-dialog');
    const deletePreview = document.getElementById('delete-design-preview');
    const deleteConfirmBtn = document.getElementById('delete-design-confirm');
    const deleteCancelBtn = document.getElementById('delete-design-cancel');
    let pendingDeleteItem = null;

    const deleteDesign = async (item) => {
        console.log('LOGGING: [gallery] deleting saved design', item.id);
        try {
            galleryItems = await userStore.deleteDesign(item.id);
        } catch (error) {
            console.error('LOGGING: [gallery] could not delete saved design', item.id, error);
            window.alert('That design could not be deleted. Please try again.');
            return;
        }
        renderGallery();
    };

    // Deleting cannot be undone, so it always asks first, showing the design in question.
    const confirmDeleteDesign = (item) => {
        if (!deleteDialog || typeof deleteDialog.showModal !== 'function') {
            if (window.confirm('Delete this saved design? This cannot be undone.')) deleteDesign(item);
            return;
        }
        pendingDeleteItem = item;
        deletePreview.innerHTML = '';
        if (item.thumbnail) {
            const image = document.createElement('img');
            image.src = item.thumbnail;
            image.alt = '';
            deletePreview.appendChild(image);
        } else if (item.svg) {
            deletePreview.innerHTML = item.svg;
        }
        console.log('LOGGING: [gallery] asking to confirm delete of', item.id);
        deleteDialog.showModal();
        deleteCancelBtn.focus();
    };

    if (deleteDialog && typeof deleteDialog.showModal === 'function') {
        deleteCancelBtn.addEventListener('click', () => deleteDialog.close('cancel'));
        deleteConfirmBtn.addEventListener('click', () => deleteDialog.close('delete'));
        // A click on the backdrop (the dialog element itself, outside its content) cancels
        deleteDialog.addEventListener('click', (event) => {
            if (event.target === deleteDialog) deleteDialog.close('cancel');
        });
        deleteDialog.addEventListener('close', () => {
            const item = pendingDeleteItem;
            pendingDeleteItem = null;
            deletePreview.innerHTML = '';
            if (deleteDialog.returnValue === 'delete' && item) {
                deleteDesign(item);
            } else {
                console.log('LOGGING: [gallery] delete cancelled');
            }
        });
    }

    saveBtn.addEventListener('click', async () => {
        if (!mandalaDesign.querySelector('svg')) return;
        const originalText = 'Save Design';
        saveBtn.disabled = true;
        saveBtn.textContent = 'Saving...';
        try {
            await saveToGallery(currentDesignParams || {
                seed: activeSeed,
                num_rings: numRingsSlider.value,
                num_divisions: numDivisionsSlider.value,
                complexity: complexitySlider.value,
                min_pattern_size: minPatternSizeSlider.value,
                categories: getSelectedCategories(),
                vary_divisions: varyDivisionsCheck.checked,
                max_region_cap: maxRegionCapCheck.checked
            }, currentRingSeeds);
            saveBtn.textContent = 'Saved!';
            saveBtn.classList.add('is-saved');
        } catch (error) {
            console.error('LOGGING: [gallery] could not save design', error);
            saveBtn.textContent = 'Save failed';
        }
        saveBtn.disabled = false;
        setTimeout(() => {
            saveBtn.textContent = originalText;
            saveBtn.classList.remove('is-saved');
        }, 1000);
    });

    // ==========================================================================
    // PREFERENCES: collapsible sections and theme
    // ==========================================================================

    const collapsibleSections = Array.from(document.querySelectorAll('details.collapsible-section[data-section]'));

    const readExpandedSections = () => {
        const expanded = {};
        collapsibleSections.forEach(section => {
            expanded[section.dataset.section] = section.open;
        });
        return expanded;
    };

    const applyExpandedSections = (expanded) => {
        if (!expanded || typeof expanded !== 'object') return;
        collapsibleSections.forEach(section => {
            const key = section.dataset.section;
            if (Object.prototype.hasOwnProperty.call(expanded, key)) {
                section.open = !!expanded[key];
            }
        });
        console.log('LOGGING: [prefs] applied expanded sections', expanded);
    };

    const sameExpanded = (a, b) => {
        const keys = new Set([...Object.keys(a || {}), ...Object.keys(b || {})]);
        for (const key of keys) {
            if (!!(a || {})[key] !== !!(b || {})[key]) return false;
        }
        return true;
    };

    collapsibleSections.forEach(section => {
        // toggle also fires when a saved preference opens or closes a section; the comparison
        // keeps that from writing the same preference straight back.
        section.addEventListener('toggle', () => {
            const expanded = readExpandedSections();
            if (sameExpanded(expanded, userStore.prefs().expandedSections)) return;
            console.log(`LOGGING: [prefs] section "${section.dataset.section}" ${section.open ? 'expanded' : 'collapsed'}`);
            userStore.savePrefs({ expandedSections: expanded });
        });
    });

    document.addEventListener('mandalaforge:themechange', (event) => {
        const theme = event.detail && event.detail.theme;
        if (!theme || userStore.prefs().theme === theme) return;
        console.log('LOGGING: [prefs] theme changed to', theme);
        userStore.savePrefs({ theme });
    });

    // Bring the page in line with preferences loaded from the account.
    const applyPrefs = (prefs) => {
        applyExpandedSections(prefs.expandedSections);
        const themeApi = window.MandalaForgeTheme;
        if (!themeApi) return;
        if (prefs.theme && prefs.theme !== themeApi.current()) {
            console.log('LOGGING: [prefs] applying saved theme', prefs.theme);
            themeApi.set(prefs.theme);
        } else if (!prefs.theme) {
            // A theme picked on this browser before preferences were saved to the account
            let localChoice = null;
            try {
                localChoice = window.localStorage.getItem(themeApi.STORAGE_KEY);
            } catch (error) {
                localChoice = null;
            }
            if (localChoice === 'light' || localChoice === 'dark') {
                console.log('LOGGING: [prefs] carrying this browser\'s theme choice into preferences', localChoice);
                userStore.savePrefs({ theme: localChoice });
            }
        }
    };

    // ==========================================================================
    // ZOOM FUNCTIONALITY
    // ==========================================================================

    const updateZoom = () => {
        paperSheet.style.transform = `scale(${currentZoom}) translate(${sheetPosition.x}px, ${sheetPosition.y}px)`;
        zoomLevelSpan.textContent = Math.round(currentZoom * 100) + '%';
        paperSheet.classList.toggle('zoomed', currentZoom > 1);
    };

    const zoomIn = () => {
        currentZoom = Math.min(currentZoom * 1.25, 5);
        updateZoom();
    };

    const zoomOut = () => {
        currentZoom = Math.max(currentZoom / 1.25, 0.25);
        if (currentZoom <= 1) {
            sheetPosition = { x: 0, y: 0 };
        }
        updateZoom();
    };

    const fitToPage = () => {
        currentZoom = 1;
        sheetPosition = { x: 0, y: 0 };
        updateZoom();
    };

    zoomInBtn.addEventListener('click', zoomIn);
    zoomOutBtn.addEventListener('click', zoomOut);
    fitToPageBtn.addEventListener('click', fitToPage);

    // Mouse wheel zoom
    pagePreview.addEventListener('wheel', (e) => {
        e.preventDefault();
        if (e.deltaY < 0) {
            zoomIn();
        } else {
            zoomOut();
        }
    });

    // Drag when zoomed
    paperSheet.addEventListener('mousedown', (e) => {
        if (currentZoom > 1) {
            isDragging = true;
            dragStart.x = e.clientX - sheetPosition.x;
            dragStart.y = e.clientY - sheetPosition.y;
        }
    });

    document.addEventListener('mousemove', (e) => {
        if (isDragging && currentZoom > 1) {
            sheetPosition.x = e.clientX - dragStart.x;
            sheetPosition.y = e.clientY - dragStart.y;
            updateZoom();
        }
    });

    document.addEventListener('mouseup', () => {
        isDragging = false;
    });

    // ==========================================================================
    // PRINT
    // ==========================================================================

    const preparePrintLayout = () => {
        const currentSvg = mandalaDesign.querySelector('svg');
        printDesign.innerHTML = '';

        if (!currentSvg) {
            return false;
        }

        const svgClone = currentSvg.cloneNode(true);
        svgClone.querySelectorAll('.selected-ring').forEach(node => {
            node.classList.remove('selected-ring');
        });
        svgClone.removeAttribute('style');
        if (!svgClone.getAttribute('viewBox')) {
            const sourceWidth = parseFloat(currentSvg.getAttribute('width'));
            const sourceHeight = parseFloat(currentSvg.getAttribute('height'));
            if (sourceWidth > 0 && sourceHeight > 0) {
                svgClone.setAttribute('viewBox', `0 0 ${sourceWidth} ${sourceHeight}`);
            }
        }
        svgClone.setAttribute('preserveAspectRatio', 'xMidYMid meet');
        svgClone.setAttribute('focusable', 'false');
        printDesign.appendChild(svgClone);

        const includeParams = includeParamsCheck.checked;
        document.body.classList.toggle('print-params', includeParams);
        printParamsPage.setAttribute('aria-hidden', includeParams ? 'false' : 'true');
        printRoot.setAttribute('aria-hidden', 'false');

        return true;
    };

    const resetPrintLayout = () => {
        printRoot.setAttribute('aria-hidden', 'true');
        printParamsPage.setAttribute('aria-hidden', 'true');
    };

    printBtn.addEventListener('click', () => {
        if (preparePrintLayout()) {
            window.print();
        }
    });

    window.addEventListener('beforeprint', preparePrintLayout);
    window.addEventListener('afterprint', resetPrintLayout);

    includeParamsCheck.addEventListener('change', () => {
        document.body.classList.toggle('print-params', includeParamsCheck.checked);
    });

    // ==========================================================================
    // INITIALIZATION
    // ==========================================================================

    const initialize = () => {
        // Set initial display values
        sliderControls.forEach(updateSliderDisplay);

        // Sections as they were last left on this browser, before the account copy arrives
        applyExpandedSections(userStore.prefs().expandedSections);

        // Saved designs load in the background; the gallery says so meanwhile
        renderGallery();

        // Generate initial mandala
        generateMandala();

        userStore.connect()
            .then(() => {
                applyPrefs(userStore.prefs());
                return userStore.loadDesigns();
            })
            .then((designs) => {
                galleryItems = designs;
            })
            .catch((error) => {
                console.error('LOGGING: [store] could not load saved designs', error);
                galleryItems = userStore.designs();
            })
            .then(() => {
                galleryLoading = false;
                renderGallery();
            });
    };

    initialize();
}

// The theme toggle needs static/theme.js. Pages load it in <head> so the right theme paints first; a
// page that does not (an older sign-in shell) gets it here, from the same folder as this script, so
// the toggle still works there, just after a brief flash of the default theme.
const COLORING_SCRIPT_SRC = document.currentScript ? document.currentScript.src : '';

function ensureThemeScript() {
    if (window.MandalaForgeTheme) {
        console.log('LOGGING: [theme] theme.js already loaded by the page');
        window.MandalaForgeTheme.sync();
        return;
    }
    if (!COLORING_SCRIPT_SRC) {
        console.warn('LOGGING: [theme] cannot locate theme.js: script.js has no src');
        return;
    }
    const themeSrc = new URL('theme.js', COLORING_SCRIPT_SRC).href;
    console.log('LOGGING: [theme] page did not load theme.js, loading', themeSrc);
    const script = document.createElement('script');
    script.src = themeSrc;
    script.addEventListener('error', () => console.error('LOGGING: [theme] failed to load', themeSrc));
    document.head.appendChild(script);
}

ensureThemeScript();

// Start once the DOM is ready. A page that adds this script after load (coloring.husted.dev does, once
// sign-in is confirmed) has already passed DOMContentLoaded, so in that case it starts at once.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initColoringApp);
} else {
    initColoringApp();
}
