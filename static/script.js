/**
 * Mandala Coloring Page Generator - Frontend Script
 *
 * Handles:
 * - Parameter controls (rings, divisions, complexity, categories)
 * - Live preview generation
 * - Gallery management
 * - Zoom and print functionality
 */

document.addEventListener('DOMContentLoaded', () => {
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

    // State
    let activeSeed = null;
    let galleryItems = JSON.parse(localStorage.getItem('mandalaGallery') || '[]');
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
        categories: getSelectedCategories()
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

    const validationStatus = document.getElementById('validation-status');
    const debugBar = document.getElementById('debug-bar');
    const debugBarValues = document.getElementById('debug-bar-values');
    const debugCopy = document.getElementById('debug-copy');
    let lastDebugText = '';

    // Every value needed to reproduce the design on screen. Without this a
    // report of "this one looks wrong" cannot be turned back into a test case.
    const renderDebugBar = (payload, data) => {
        if (!debugBar || !debugBarValues) return;
        const rings = (data.pattern_usage || [])
            .filter(entry => entry.variation_index === 0)
            .sort((a, b) => a.ring_index - b.ring_index)
            .map(entry => `R${entry.ring_index + 1}=${entry.name.replace(/^smart_/, '')}`);
        const parts = [
            `seed=${data.used_seed}`,
            `rings=${payload.num_rings}`,
            `divisions=${payload.num_divisions}`,
            `minSize=${payload.min_pattern_size}`,
            `complexity=${payload.complexity}`,
            `categories=${(payload.categories || []).join('+')}`,
        ];
        if (data.validation) {
            parts.push(`valid=${data.validation.is_valid}`);
            if (!data.validation.is_valid) parts.push(`issues=${data.validation.issue_count}`);
        }
        lastDebugText = parts.concat(rings).join('  ');
        debugBarValues.textContent = lastDebugText;
        debugBar.hidden = false;
        debugBar.classList.toggle('is-invalid', !!data.validation && !data.validation.is_valid);
    };

    if (debugCopy) {
        debugCopy.addEventListener('click', async () => {
            if (!lastDebugText) return;
            try {
                await navigator.clipboard.writeText(lastDebugText);
                debugCopy.textContent = 'Copied';
            } catch (err) {
                debugCopy.textContent = 'Copy failed';
            }
            setTimeout(() => { debugCopy.textContent = 'Copy'; }, 1200);
        });
    }

    let currentPatternUsage = [];

    // The QA pipeline decides whether a design is actually colourable, so show
    // the verdict instead of leaving it in a print-only field.
    const renderValidationStatus = (validation) => {
        if (!validationStatus) return;
        if (!validation) {
            validationStatus.hidden = true;
            return;
        }
        validationStatus.hidden = false;
        validationStatus.classList.toggle('is-valid', validation.is_valid);
        validationStatus.classList.toggle('is-invalid', !validation.is_valid);
        validationStatus.textContent = validation.is_valid
            ? 'Checked: all lines connect, every space is colourable'
            : `Check found ${validation.issue_count} issue${validation.issue_count === 1 ? '' : 's'}`;
        validationStatus.title = validation.is_valid
            ? ''
            : (validation.issues || []).slice(0, 8).join('\n');
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
            const used = currentPatternUsage.find(entry => entry.ring_index === ringIndex);
            button.textContent = `Ring ${ringIndex + 1}`;
            if (used && used.name) {
                // pattern_usage was returned by the API but never shown; the
                // name is the most useful thing to know before re-rolling a ring
                const pretty = used.name.replace(/^smart_/, '').replace(/_/g, ' ');
                button.title = `Ring ${ringIndex + 1}: ${pretty}`;
                const tag = document.createElement('span');
                tag.className = 'ring-pattern-name';
                tag.textContent = pretty;
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
    // GENERATE MANDALA
    // ==========================================================================

    const generateMandala = async () => {
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

        const payload = buildGenerationPayload(seedForGeneration);

        console.log('Sending payload:', payload);
        resetRingSelection();
        mandalaDesign.innerHTML = '<div class="loader">Generating...</div>';

        try {
            const response = await fetch('/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            mandalaDesign.innerHTML = data.svg;
            activeSeed = data.used_seed;
            currentDesignParams = { ...payload, seed: data.used_seed };
            currentPatternUsage = data.pattern_usage || [];
            syncPendingParameterIndicators();
            prepareRingSelection();
            let validationText = '';
            if (data.validation) {
                validationText = `\nValidation: ${data.validation.is_valid ? 'passed' : 'failed'} (${data.validation.issue_count} issues)`;
                if (!data.validation.is_valid) {
                    console.warn('Mandala validation issues:', data.validation.issues);
                }
            }
            renderValidationStatus(data.validation);
            renderDebugBar(payload, data);
            paramsText.textContent = data.params_string + validationText;

        } catch (error) {
            console.error("Error generating mandala:", error);
            resetRingSelection();
            mandalaDesign.innerHTML = `<div class="error">Failed to generate mandala: ${error.message}</div>`;
        }
    };

    const parseSvgFragment = (fragment) => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(
            `<svg xmlns="http://www.w3.org/2000/svg">${fragment}</svg>`,
            'image/svg+xml'
        );

        if (doc.querySelector('parsererror')) {
            throw new Error('Invalid SVG fragment returned by server');
        }

        return Array.from(doc.documentElement.children).map(node => (
            document.importNode(node, true)
        ));
    };

    const regenerateSelectedRing = async () => {
        if (selectedRingIndex === null || !currentDesignParams) return;

        const currentSvg = mandalaDesign.querySelector('svg');
        if (!currentSvg) return;

        const ringSeed = Math.floor(Math.random() * 1000000);
        const payload = {
            ...currentDesignParams,
            ring_index: selectedRingIndex,
            ring_seed: ringSeed
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

            const defs = currentSvg.querySelector('defs');
            if (!defs) {
                throw new Error('Current SVG has no defs section');
            }

            defs.querySelectorAll(`g[id^="ring-${selectedRingIndex}-var-"]`).forEach(node => {
                node.remove();
            });

            parseSvgFragment(data.defs_svg).forEach(node => {
                defs.appendChild(node);
            });

            const oldRing = currentSvg.querySelector(`#mandala > g#ring-${selectedRingIndex}`);
            const newRing = parseSvgFragment(data.ring_svg)[0];
            if (!oldRing || !newRing) {
                throw new Error('Could not replace selected ring');
            }

            oldRing.replaceWith(newRing);
            currentDesignParams = { ...currentDesignParams };
            syncPendingParameterIndicators();
            renderRingSelector();
            selectRing(newRing);

            if (data.validation) {
                const validationText = `\nValidation: ${data.validation.is_valid ? 'passed' : 'failed'} (${data.validation.issue_count} issues)`;
                paramsText.textContent = paramsText.textContent.replace(/\nValidation:.*$/s, '') + validationText;
                if (!data.validation.is_valid) {
                    console.warn('Ring validation issues:', data.validation.issues);
                }
            }
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

        // Update displays
        sliderControls.forEach(updateSliderDisplay);

        // Randomize categories (ensure at least one is checked)
        const allCats = [catBotanical, catGeometric, catCeltic, catArtDeco, catAbstract];
        allCats.forEach(cat => cat.checked = Math.random() > 0.5);

        // Ensure at least one category
        if (getSelectedCategories().length === 0) {
            allCats[Math.floor(Math.random() * allCats.length)].checked = true;
        }

        activeSeed = createRandomSeed();
        seedInput.value = activeSeed;
        generateMandala();
    });

    // ==========================================================================
    // GALLERY
    // ==========================================================================

    const saveToGallery = (svgContent, params) => {
        const item = {
            id: Date.now(),
            svg: svgContent,
            params: params,
            timestamp: new Date().toISOString()
        };

        galleryItems.unshift(item);
        if (galleryItems.length > 12) galleryItems = galleryItems.slice(0, 12);

        localStorage.setItem('mandalaGallery', JSON.stringify(galleryItems));
        renderGallery();
    };

    const renderGallery = () => {
        galleryGrid.innerHTML = '';

        if (galleryItems.length === 0) {
            const emptyMessage = document.createElement('div');
            emptyMessage.className = 'gallery-empty';
            emptyMessage.textContent = 'No saved designs yet. Click "Save Design" to add one!';
            galleryGrid.appendChild(emptyMessage);
            return;
        }

        galleryItems.forEach(item => {
            const galleryItem = document.createElement('div');
            galleryItem.className = 'gallery-item';
            galleryItem.innerHTML = item.svg;
            galleryItem.title = `Saved: ${new Date(item.timestamp).toLocaleString()}`;
            galleryItem.addEventListener('click', () => {
                mandalaDesign.innerHTML = item.svg;
                if (item.params) {
                    currentDesignParams = {
                        seed: item.params.seed,
                        num_rings: parseInt(item.params.num_rings),
                        num_divisions: parseInt(item.params.num_divisions),
                        complexity: parseFloat(item.params.complexity),
                        min_pattern_size: parseFloat(item.params.min_pattern_size),
                        categories: item.params.categories || ['botanical']
                    };
                    activeSeed = currentDesignParams.seed;
                    syncPendingParameterIndicators();
                }
                prepareRingSelection();
            });
            galleryGrid.appendChild(galleryItem);
        });
    };

    saveBtn.addEventListener('click', () => {
        if (mandalaDesign.querySelector('svg')) {
            saveToGallery(getCleanCurrentSvgMarkup(), currentDesignParams || {
                seed: activeSeed,
                num_rings: numRingsSlider.value,
                num_divisions: numDivisionsSlider.value,
                complexity: complexitySlider.value,
                min_pattern_size: minPatternSizeSlider.value,
                categories: getSelectedCategories()
            });

            // Visual feedback
            const originalText = saveBtn.textContent;
            saveBtn.textContent = 'Saved!';
            saveBtn.style.backgroundColor = '#28a745';
            setTimeout(() => {
                saveBtn.textContent = originalText;
                saveBtn.style.backgroundColor = '';
            }, 1000);
        }
    });

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

        // Render saved gallery
        renderGallery();

        // Generate initial mandala
        generateMandala();
    };

    initialize();
});
