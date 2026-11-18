// Visit statistics for the published site (Google Tag Manager -> Analytics), with consent.
//
// - Runs only on github.io: the editor served locally by `laniakea editor`, or opened offline,
//   sends nothing (there this file isn't even found).
// - Google consent mode v2: everything starts "denied", so no analytics cookies are set until the
//   visitor clicks Allow. Until then Analytics only gets cookieless, anonymous pings.
//   Set LOAD_BEFORE_CONSENT = false to load nothing at all before consent.
// - The choice is remembered in localStorage; any element with [data-privacy-settings] reopens it.
(function () {
  if (!location.hostname.endsWith('github.io')) return;

  const GTM_ID = 'GTM-T365MB7L';
  const KEY = 'laniakea-analytics-consent';   // 'granted' | 'denied'
  const LOAD_BEFORE_CONSENT = true;

  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  window.gtag = gtag;

  let choice = null;
  try { choice = localStorage.getItem(KEY); } catch { /* storage blocked: ask every visit */ }

  const state = (v) => ({ analytics_storage: v, ad_storage: 'denied', ad_user_data: 'denied', ad_personalization: 'denied' });
  gtag('consent', 'default', { ...state(choice === 'granted' ? 'granted' : 'denied'), wait_for_update: 500 });

  let loaded = false;
  function loadGtm() {
    if (loaded) return;
    loaded = true;
    window.dataLayer.push({ 'gtm.start': new Date().getTime(), event: 'gtm.js' });
    gtag('js', new Date());
    const s = document.createElement('script');
    s.async = true;
    s.src = `https://www.googletagmanager.com/gtm.js?id=${GTM_ID}`;
    document.head.appendChild(s);
  }
  if (LOAD_BEFORE_CONSENT || choice === 'granted') loadGtm();

  function decide(v) {
    try { localStorage.setItem(KEY, v); } catch { /* not remembered */ }
    gtag('consent', 'update', state(v));
    if (v === 'granted') loadGtm();
    hide();
  }

  // ---- banner (uses the site's colour tokens from editor/style.css)
  let banner = null;
  function show() {
    if (banner) { banner.hidden = false; return; }
    const css = document.createElement('style');
    css.textContent = `
      .lk-consent { position: fixed; left: 16px; right: 16px; bottom: 16px; z-index: 50; max-width: 720px; margin: 0 auto;
        display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between;
        padding: 12px 14px; background: var(--panel, #fff); color: var(--ink, #1b1d22);
        border: 1px solid var(--line, #dcdcd6); border-radius: 10px; box-shadow: 0 6px 24px rgba(0,0,0,.18); font-size: 13px; }
      .lk-consent p { margin: 0; flex: 1 1 320px; }
      .lk-consent .lk-actions { display: flex; gap: 8px; }`;
    document.head.appendChild(css);
    banner = document.createElement('div');
    banner.className = 'lk-consent';
    banner.setAttribute('role', 'dialog');
    banner.setAttribute('aria-label', 'Visit statistics');
    banner.innerHTML = `<p>This site counts visits with Google Analytics (via Tag Manager). May it use cookies for that?
      Firmware and waves never leave your browser either way.</p>
      <span class="lk-actions"><button type="button" data-v="denied">No thanks</button>
      <button type="button" class="primary" data-v="granted">Allow</button></span>`;
    banner.addEventListener('click', (e) => { const v = e.target.closest('button')?.dataset.v; if (v) decide(v); });
    document.body.appendChild(banner);
  }
  function hide() { if (banner) banner.hidden = true; }

  function wire() {
    if (!choice) show();
    document.addEventListener('click', (e) => {
      if (e.target.closest('[data-privacy-settings]')) { e.preventDefault(); show(); }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire); else wire();
})();
