/* Style switching never reloads the page or replaces the media element. */
(() => {
  const key = 'chordlab:theme';
  function apply(theme) {
    theme = theme === 'classic' ? 'classic' : 'studio';
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'studio' ? '#f5f7fb' : '#f5f3ed');
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
  try { saved = localStorage.getItem(key); } catch {}
  apply(saved);
  document.addEventListener('DOMContentLoaded', () => {
    apply(document.documentElement.dataset.theme);
    document.getElementById('themeSelect')?.addEventListener('change', event => {
      apply(event.target.value);
      try { localStorage.setItem(key, event.target.value); } catch {}
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && document.documentElement.dataset.theme === 'studio') {
      const utilities = document.getElementById('workspaceUtilities');
      if (utilities) utilities.open = false;
    }
  });
})();
