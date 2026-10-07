/* Style switching never reloads the page or replaces the media element. */
(() => {
  const key = 'chordlab:theme';
  const colorKey = 'chordlab:color-mode';
  const system = window.matchMedia('(prefers-color-scheme: dark)');
  let colorPreference = 'system';
  function applyColor() {
    const root = document.documentElement;
    const dark = root.dataset.theme === 'studio' && (colorPreference === 'dark' || (colorPreference === 'system' && system.matches));
    root.dataset.colorMode = dark ? 'dark' : 'light';
    root.dataset.colorPreference = colorPreference;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', root.dataset.theme === 'classic' ? '#f5f3ed' : dark ? '#131316' : '#f5f3ef');
    const select = document.getElementById('colorModeSelect');
    if (select) select.value = colorPreference;
    const menu = document.getElementById('colorMenu');
    if (menu) menu.hidden = root.dataset.theme === 'classic';
    const toggle = document.getElementById('colorToggle');
    if (toggle) {
      const label = {system: '跟隨系統', light: '淺色模式', dark: '暗色模式'}[colorPreference];
      toggle.setAttribute('aria-label', `外觀：${label}`);
      toggle.title = `外觀：${label}`;
    }
  }
  function apply(theme) {
    theme = theme === 'classic' ? 'classic' : 'studio';
    document.documentElement.dataset.theme = theme;
    applyColor();
    const select = document.getElementById('themeSelect');
    if (select) select.value = theme;
    document.querySelectorAll('details[data-studio-fold]').forEach(panel => { panel.open = theme === 'classic'; });
    const practice = document.getElementById('practiceTools'), downloads = document.getElementById('stemDownloadsPanel');
    const utilityBody = document.getElementById('workspaceUtilitiesBody');
    if (practice && downloads && utilityBody) {
      if (theme === 'studio') utilityBody.append(practice, downloads);
      else {
        document.getElementById('practiceSlot').after(practice);
        document.getElementById('downloadsSlot').after(downloads);
      }
    }
    const insight = document.querySelector('.analysis-insight'), review = document.getElementById('localChordReviewPanel');
    if (insight && review) {
      const anchor = theme === 'studio' ? document.querySelector('.timeline-wrap') : document.getElementById('chordToolsSlot');
      anchor.after(insight, review);
    }
  }
  let saved;
  try {
    saved = localStorage.getItem(key);
    const stored = localStorage.getItem(colorKey);
    if (['system', 'light', 'dark'].includes(stored)) colorPreference = stored;
  } catch {}
  apply(saved);
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.getElementById('themeSelect')?.addEventListener('change', event => {
      apply(event.target.value);
      try { localStorage.setItem(key, event.target.value); } catch {}
    });
    document.getElementById('colorModeSelect')?.addEventListener('change', event => {
      colorPreference = ['system', 'light', 'dark'].includes(event.target.value) ? event.target.value : 'system';
      applyColor();
      try { localStorage.setItem(colorKey, colorPreference); } catch {}
    });
    document.addEventListener('click', event => {
      const menu = document.getElementById('colorMenu');
      if (menu && !menu.contains(event.target)) menu.open = false;
    });
  });
  system.addEventListener('change', applyColor);
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.documentElement.dataset.theme === 'studio') {
      const utilities = document.getElementById('workspaceUtilities');
      if (utilities) utilities.open = false;
      const colors = document.getElementById('colorMenu');
      if (colors) colors.open = false;
    }
  });
})();
