/**
 * Light / dark theme for MandalaForge.
 *
 * Load this in <head>, before the stylesheet paints, so the page never flashes the wrong theme:
 *     <script src="../static/theme.js"></script>
 *
 * The theme is stored on <html data-theme="light|dark">; static/style.css keys its dark tokens off
 * that attribute. The visitor's explicit choice is kept in localStorage under STORAGE_KEY. With no
 * stored choice the page follows the operating system's prefers-color-scheme, live.
 *
 * Any element with a data-theme-toggle attribute flips the theme when clicked. Clicks are handled by
 * one delegated listener on document, so toggles that are added later (coloring.husted.dev stamps the
 * app in from a <template> after sign-in) work without being bound; call MandalaForgeTheme.sync()
 * after adding one so its label matches the current theme.
 *
 * The coloring page itself (the SVG preview, gallery thumbnails, saved files and print) is always
 * black line art on white paper, whatever the theme.
 */
(function () {
    'use strict';

    if (window.MandalaForgeTheme) {
        console.log('LOGGING: [theme] theme.js already loaded, skipping second copy');
        return;
    }

    const STORAGE_KEY = 'mandalaforge-theme';
    const THEMES = ['light', 'dark'];
    const root = document.documentElement;
    const media = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;

    function readStored() {
        try {
            const value = window.localStorage.getItem(STORAGE_KEY);
            return THEMES.includes(value) ? value : null;
        } catch (error) {
            console.warn('LOGGING: [theme] localStorage is unavailable, theme choice will not persist', error);
            return null;
        }
    }

    function writeStored(theme) {
        try {
            window.localStorage.setItem(STORAGE_KEY, theme);
        } catch (error) {
            console.warn('LOGGING: [theme] could not save theme choice', error);
        }
    }

    function systemTheme() {
        return media && media.matches ? 'dark' : 'light';
    }

    function current() {
        return root.dataset.theme === 'dark' ? 'dark' : 'light';
    }

    // Bring every toggle's label in line with the theme it will switch to.
    function sync() {
        const next = current() === 'dark' ? 'light' : 'dark';
        const label = `Switch to ${next} theme`;
        const toggles = document.querySelectorAll('[data-theme-toggle]');
        toggles.forEach((toggle) => {
            toggle.setAttribute('aria-label', label);
            toggle.setAttribute('title', label);
        });
        return toggles.length;
    }

    function apply(theme, reason) {
        root.dataset.theme = theme;
        root.style.colorScheme = theme;
        const toggleCount = sync();
        console.log(`LOGGING: [theme] applied ${theme} theme (${reason}); ${toggleCount} toggle(s) updated`);
    }

    function set(theme) {
        if (!THEMES.includes(theme)) {
            console.warn('LOGGING: [theme] ignoring unknown theme', theme);
            return;
        }
        writeStored(theme);
        apply(theme, 'chosen by visitor');
    }

    function toggle() {
        set(current() === 'dark' ? 'light' : 'dark');
    }

    const stored = readStored();
    apply(stored || systemTheme(), stored ? 'saved choice' : 'operating system preference');

    document.addEventListener('click', (event) => {
        const target = event.target;
        if (!target || typeof target.closest !== 'function') return;
        if (!target.closest('[data-theme-toggle]')) return;
        console.log('LOGGING: [theme] toggle clicked');
        toggle();
    });

    // Follow the OS while the visitor has not picked a theme themselves.
    if (media) {
        const onSystemChange = () => {
            if (readStored()) {
                console.log('LOGGING: [theme] OS theme changed, keeping saved choice');
                return;
            }
            apply(systemTheme(), 'operating system preference changed');
        };
        if (typeof media.addEventListener === 'function') {
            media.addEventListener('change', onSystemChange);
        } else if (typeof media.addListener === 'function') {
            media.addListener(onSystemChange);
        }
    }

    // Keep other open tabs in step when the choice changes in one of them.
    window.addEventListener('storage', (event) => {
        if (event.key !== STORAGE_KEY) return;
        const value = THEMES.includes(event.newValue) ? event.newValue : systemTheme();
        apply(value, 'changed in another tab');
    });

    // Toggles in the page body do not exist yet while this runs in <head>.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => sync());
    }

    window.MandalaForgeTheme = { STORAGE_KEY, current, set, toggle, sync };
})();
