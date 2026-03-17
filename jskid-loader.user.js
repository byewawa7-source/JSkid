// ==UserScript==
// @name         JSkid Loader
// @namespace    https://github.com/jskid/jskid
// @version      1.0.0
// @description  Loads JSkid – the JanitorAI power-user framework – from GitHub
// @author       JSkid
// @match        https://janitorai.com/*
// @match        https://www.janitorai.com/*
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @grant        GM_deleteValue
// @grant        GM_listValues
// @grant        GM_addStyle
// @grant        unsafeWindow
// @run-at       document-idle
// @connect      raw.githubusercontent.com
// @connect      janitorai.com
// ==/UserScript==

(function () {
  'use strict';

  // ─── CONFIG ───────────────────────────────────────────────────────────────
  const JSKID_CORE_URL =
    'https://raw.githubusercontent.com/byewawa7-source/JSkid/refs/heads/main/jskid-core.js';
  const CACHE_KEY   = 'jskid_core_cache';
  const CACHE_TTL   = 1000 * 60 * 60; // 1 hour
  const FORCE_KEY   = 'jskid_force_reload';

  // Expose GM APIs to the core so it doesn't need @grant itself
  unsafeWindow.__jskidGM = {
    getValue:    (k, d)    => GM_getValue(k, d),
    setValue:    (k, v)    => GM_setValue(k, v),
    deleteValue: (k)       => GM_deleteValue(k),
    listValues:  ()        => GM_listValues(),
    addStyle:    (css)     => GM_addStyle(css),
  };

  function loadCore(code) {
    try {
      const fn = new Function(code); // eslint-disable-line no-new-func
      fn();
    } catch (e) {
      console.error('[JSkid Loader] Failed to execute core:', e);
      showError(e.message);
    }
  }

  function showError(msg) {
    const d = document.createElement('div');
    d.style.cssText =
      'position:fixed;bottom:20px;right:20px;background:#ff4444;color:#fff;' +
      'padding:12px 18px;border-radius:8px;z-index:999999;font-family:monospace;max-width:340px';
    d.textContent = '⚠️ JSkid failed to load: ' + msg;
    document.body.appendChild(d);
    setTimeout(() => d.remove(), 8000);
  }

  function fetchAndCache(url, cb) {
    GM_xmlhttpRequest({
      method: 'GET',
      url: url + '?t=' + Date.now(),
      onload(res) {
        if (res.status === 200) {
          GM_setValue(CACHE_KEY, JSON.stringify({ code: res.responseText, ts: Date.now() }));
          GM_setValue(FORCE_KEY, false);
          cb(res.responseText);
        } else {
          console.warn('[JSkid Loader] Remote fetch failed, trying cache...');
          const cached = GM_getValue(CACHE_KEY, null);
          if (cached) {
            cb(JSON.parse(cached).code);
          } else {
            showError('Could not fetch JSkid core (HTTP ' + res.status + ')');
          }
        }
      },
      onerror(e) {
        console.warn('[JSkid Loader] Network error, trying cache...', e);
        const cached = GM_getValue(CACHE_KEY, null);
        if (cached) {
          cb(JSON.parse(cached).code);
        } else {
          showError('Network error and no cache available.');
        }
      },
    });
  }

  function init() {
    const forceReload = GM_getValue(FORCE_KEY, false);
    const raw = GM_getValue(CACHE_KEY, null);

    if (!forceReload && raw) {
      try {
        const { code, ts } = JSON.parse(raw);
        if (Date.now() - ts < CACHE_TTL) {
          loadCore(code);
          return;
        }
      } catch (_) { /* corrupt cache, re-fetch */ }
    }

    fetchAndCache(JSKID_CORE_URL, loadCore);
  }

  // Wait until body exists
  if (document.body) {
    init();
  } else {
    document.addEventListener('DOMContentLoaded', init);
  }
})();
