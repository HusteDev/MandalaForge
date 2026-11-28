/**
 * "How to use" slideshow: a modal dialog that walks through the page one step
 * per slide, each with a screenshot from static/help/ and a short instruction.
 * Arrow keys or the arrow buttons move between steps; Esc or the close button
 * (or a click on the backdrop) closes it.
 */
function initColoringHelp() {
    const HELP_STEPS = [
        {
            image: 'step-1-overview.jpg',
            title: 'Welcome to MandalaForge',
            text: 'The main buttons stay at the top of the left panel; the settings sit below them in sections you can open or close with a click on their title. MandalaForge remembers which sections you left open, and your light or dark choice. Your coloring page preview is on the right, and a design is generated as soon as the page opens.'
        },
        {
            image: 'step-2-settings.jpg',
            title: 'Adjust the size and detail',
            text: 'Drag the sliders to set the number of rings, the divisions around the center, the smallest pattern size and, further down, the detail level. A changed slider shows "not applied" until you generate again.'
        },
        {
            image: 'step-3-categories.jpg',
            title: 'Pick pattern categories',
            text: 'Tick one or more categories to choose which kinds of patterns appear. At least one must be selected.'
        },
        {
            image: 'step-4-generate.jpg',
            title: 'Generate a design',
            text: 'Click Generate for a new design using your settings. Click the dice to shuffle every setting and generate something completely random. When a design finishes, a short note pops up to confirm every space can be colored.'
        },
        {
            image: 'step-5-ring.jpg',
            title: 'Re-roll a single ring',
            text: 'In the Rings section, choose a ring with the Ring buttons, or click a ring in the preview, then click Regenerate Ring to replace just that ring and keep the rest.'
        },
        {
            image: 'step-6-zoom.jpg',
            title: 'Zoom in for a closer look',
            text: 'Use + and - (or your mouse wheel) to zoom, drag the page to move around, and click Fit to Page to reset the view.'
        },
        {
            image: 'step-7-save.jpg',
            title: 'Save designs you like',
            text: 'Click Save Design to keep the current design. Saved designs appear in the Saved Designs section at the bottom of the panel; click one to open it again, or click the x in its corner to delete it.'
        },
        {
            image: 'step-8-print.jpg',
            title: 'Print your coloring page',
            text: 'Click Print to print the design on its own page. Tick "Include parameters on print" to add a second page listing the settings to enter to make the same design again.'
        }
    ];

    const helpBtn = document.getElementById('help-btn');
    const dialog = document.getElementById('help-dialog');
    if (!helpBtn || !dialog || typeof dialog.showModal !== 'function') return;

    const closeBtn = document.getElementById('help-close');
    const prevBtn = document.getElementById('help-prev');
    const nextBtn = document.getElementById('help-next');
    const image = document.getElementById('help-image');
    const stepCount = document.getElementById('help-step-count');
    const stepTitle = document.getElementById('help-step-title');
    const stepText = document.getElementById('help-step-text');
    const dots = document.getElementById('help-dots');
    const imageBase = '../static/help/';

    let current = 0;

    const dotButtons = HELP_STEPS.map((step, index) => {
        const dot = document.createElement('button');
        dot.type = 'button';
        dot.className = 'help-dot';
        dot.setAttribute('role', 'tab');
        dot.setAttribute('aria-label', `Step ${index + 1}: ${step.title}`);
        dot.addEventListener('click', () => show(index));
        dots.appendChild(dot);
        return dot;
    });

    function show(index) {
        current = Math.max(0, Math.min(HELP_STEPS.length - 1, index));
        const step = HELP_STEPS[current];
        image.src = imageBase + step.image;
        image.alt = `Screenshot: ${step.title}`;
        stepCount.textContent = `Step ${current + 1} of ${HELP_STEPS.length}`;
        stepTitle.textContent = step.title;
        stepText.textContent = step.text;
        prevBtn.disabled = current === 0;
        nextBtn.disabled = current === HELP_STEPS.length - 1;
        dotButtons.forEach((dot, i) => {
            const active = i === current;
            dot.classList.toggle('active', active);
            dot.setAttribute('aria-selected', active ? 'true' : 'false');
        });
        // Warm the next image so the slide change feels instant
        const upcoming = HELP_STEPS[current + 1];
        if (upcoming) new Image().src = imageBase + upcoming.image;
    }

    helpBtn.addEventListener('click', () => {
        show(0);
        dialog.showModal();
        nextBtn.focus();
    });

    closeBtn.addEventListener('click', () => dialog.close());
    prevBtn.addEventListener('click', () => show(current - 1));
    nextBtn.addEventListener('click', () => show(current + 1));

    // A click on the backdrop lands on the dialog element itself
    dialog.addEventListener('click', (event) => {
        if (event.target === dialog) dialog.close();
    });

    dialog.addEventListener('keydown', (event) => {
        if (event.key === 'ArrowRight') {
            event.preventDefault();
            show(current + 1);
        } else if (event.key === 'ArrowLeft') {
            event.preventDefault();
            show(current - 1);
        }
    });

    dialog.addEventListener('close', () => helpBtn.focus());
}

// Start once the DOM is ready. A page that adds this script after load (coloring.husted.dev does, once
// sign-in is confirmed) has already passed DOMContentLoaded, so in that case it starts at once.
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initColoringHelp);
} else {
    initColoringHelp();
}
