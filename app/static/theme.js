/* Style switching never reloads the page or replaces the media element. */
(() => {
  const key = 'chordlab:theme';
  function apply(theme) {
    theme = theme === 'classic' ? 'classic' : 'studio';
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'studio' ? '#f5f7fb' : '#f5f3ed');
    const select = document.getElementById('themeSelect');
    if (select) select.value = theme;
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
})();
