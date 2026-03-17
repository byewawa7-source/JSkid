/* ============================================================
   JSkid Core  v1.0.0
   The JanitorAI power-user framework.
   Hosted on GitHub — loaded by jskid-loader.user.js
   ============================================================ */
;(function (global) {
  'use strict';

  if (global.__JSKID__) return; // already running

  const VERSION  = '1.0.0';
  const GM       = global.__jskidGM || {
    getValue:    (k, d)  => { try { return JSON.parse(localStorage.getItem('jskid_' + k)); } catch { return d; } },
    setValue:    (k, v)  => localStorage.setItem('jskid_' + k, JSON.stringify(v)),
    deleteValue: (k)     => localStorage.removeItem('jskid_' + k),
    listValues:  ()      => Object.keys(localStorage).filter(k => k.startsWith('jskid_')).map(k => k.slice(6)),
    addStyle:    (css)   => { const s = document.createElement('style'); s.textContent = css; document.head.appendChild(s); return s; },
  };

  /* ─── CHANGELOG ────────────────────────────────────────────────────────── */
  const CHANGELOG = [
    {
      version: '1.0.0',
      date: '2025-01-01',
      notes: [
        '🎉 Initial release of JSkid',
        '🧩 Addon system with dependency resolution',
        '✏️ JSkript interpreter for character behaviour scripting',
        '🛠️ Tool injection system',
        '🎨 Theme engine (colors, wallpapers, animated backgrounds)',
        '⚙️ 40+ tweaks for JanitorAI',
        '🖼️ Design system (Default, Minimal, Terminal, Floating Windows, Cozy)',
        '🔄 GitHub-based auto-update via loader',
      ],
    },
  ];

  /* ─── UTILITIES ─────────────────────────────────────────────────────────── */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  function el(tag, attrs = {}, ...children) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === 'style' && typeof v === 'object') Object.assign(e.style, v);
      else if (k.startsWith('on')) e.addEventListener(k.slice(2).toLowerCase(), v);
      else e.setAttribute(k, v);
    }
    for (const c of children.flat()) {
      if (c == null) continue;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return e;
  }

  function debounce(fn, ms) {
    let t;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  function deepMerge(target, source) {
    for (const k of Object.keys(source)) {
      if (source[k] && typeof source[k] === 'object' && !Array.isArray(source[k])) {
        target[k] = target[k] || {};
        deepMerge(target[k], source[k]);
      } else {
        target[k] = source[k];
      }
    }
    return target;
  }

  function uuid() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = Math.random() * 16 | 0;
      return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  /* ─── STORAGE ───────────────────────────────────────────────────────────── */
  const Store = {
    get(key, def = null) {
      const v = GM.getValue('data_' + key, undefined);
      return v === undefined ? def : v;
    },
    set(key, value) { GM.setValue('data_' + key, value); },
    del(key)        { GM.deleteValue('data_' + key); },
    getObj(key, def = {}) {
      const v = this.get(key, null);
      return v ? (typeof v === 'object' ? v : JSON.parse(v)) : def;
    },
    setObj(key, value) { this.set(key, value); },
  };

  /* ─── EVENT BUS ─────────────────────────────────────────────────────────── */
  class EventBus {
    constructor() { this._listeners = {}; }
    on(evt, fn)  { (this._listeners[evt] = this._listeners[evt] || []).push(fn); }
    off(evt, fn) { this._listeners[evt] = (this._listeners[evt] || []).filter(f => f !== fn); }
    once(evt, fn) {
      const wrapper = (...a) => { fn(...a); this.off(evt, wrapper); };
      this.on(evt, wrapper);
    }
    emit(evt, ...args) {
      for (const fn of (this._listeners[evt] || [])) {
        try { fn(...args); } catch (e) { console.error('[JSkid EventBus]', e); }
      }
    }
  }

  const bus = new EventBus();

  /* ─── FETCH INTERCEPTOR ─────────────────────────────────────────────────── */
  const _origFetch = global.fetch.bind(global);
  const _hooks     = { beforeSend: [], afterReceive: [] };

  global.fetch = async function (input, init = {}) {
    let url  = typeof input === 'string' ? input : input.url;
    let opts = { ...init };

    for (const hook of _hooks.beforeSend) {
      try {
        const result = await hook(url, opts);
        if (result) ({ url, opts } = result);
      } catch (e) { console.error('[JSkid hook:beforeSend]', e); }
    }

    const req = typeof input === 'string' ? new Request(url, opts) : new Request(input, opts);
    let res = await _origFetch(req);

    for (const hook of _hooks.afterReceive) {
      try { res = await hook(url, res) || res; } catch (e) { console.error('[JSkid hook:afterReceive]', e); }
    }

    bus.emit('fetch', url, res.clone());
    return res;
  };

  /* ─── JANITOR API WRAPPER ───────────────────────────────────────────────── */
  class JSkidAPI {
    constructor() {
      this._charCache = {};
      this._chatCache = {};

      bus.on('fetch', (url, res) => {
        if (url.includes('/hampter/characters/') && !url.includes('/messages')) {
          res.clone().json().then(d => {
            if (d && d.id) this._charCache[d.id] = d;
          }).catch(() => {});
        }
        if (url.includes('/hampter/chats/') && !url.includes('/messages')) {
          res.clone().json().then(d => {
            if (d && d.id) this._chatCache[d.id] = d;
          }).catch(() => {});
        }
      });
    }

    _headers() {
      return { 'Content-Type': 'application/json', 'x-app-version': '7.9.1' };
    }

    /* Characters */
    async getCharacter(id) {
      if (this._charCache[id]) return this._charCache[id];
      const r = await _origFetch(`/hampter/characters/${id}`, { headers: this._headers() });
      if (!r.ok) return null;
      const d = await r.json();
      this._charCache[id] = d;
      return d;
    }

    async searchCharacters(query, page = 1) {
      const r = await _origFetch(`/hampter/characters?search=${encodeURIComponent(query)}&page=${page}`, { headers: this._headers() });
      return r.ok ? r.json() : null;
    }

    async getTrendingCharacters(page = 1) {
      const r = await _origFetch(`/hampter/characters?page=${page}&sort=trending`, { headers: this._headers() });
      return r.ok ? r.json() : null;
    }

    /* Chats */
    async getChat(id) {
      if (this._chatCache[id]) return this._chatCache[id];
      const r = await _origFetch(`/hampter/chats/${id}`, { headers: this._headers() });
      if (!r.ok) return null;
      const d = await r.json();
      this._chatCache[d.id] = d;
      return d;
    }

    async listChats() {
      const r = await _origFetch('/hampter/chats', { headers: this._headers() });
      return r.ok ? r.json() : null;
    }

    async createChat(characterId) {
      const r = await _origFetch('/hampter/chats', {
        method: 'POST',
        headers: this._headers(),
        body: JSON.stringify({ character_id: characterId }),
      });
      return r.ok ? r.json() : null;
    }

    /* Messages */
    async sendMessage(chatId, content, role = 'user') {
      const r = await _origFetch(`/hampter/chats/${chatId}/messages`, {
        method: 'POST',
        headers: this._headers(),
        body: JSON.stringify({ role, content }),
      });
      return r.ok ? r.json() : null;
    }

    async editMessage(chatId, messageId, content) {
      const r = await _origFetch(`/hampter/chats/${chatId}/messages/${messageId}`, {
        method: 'PATCH',
        headers: this._headers(),
        body: JSON.stringify({ content }),
      });
      return r.ok ? r.json() : null;
    }

    async deleteMessage(chatId, messageId) {
      const r = await _origFetch(`/hampter/chats/${chatId}/messages/${messageId}`, {
        method: 'DELETE',
        headers: this._headers(),
      });
      return r.ok;
    }

    async getMessages(chatId) {
      const r = await _origFetch(`/hampter/chats/${chatId}/messages`, { headers: this._headers() });
      return r.ok ? r.json() : null;
    }

    /* Generation (SSE streaming) */
    async generate(chatId, onChunk, onDone) {
      const r = await _origFetch('/generateAlpha', {
        method: 'POST',
        headers: { ...this._headers(), Accept: 'text/event-stream' },
        body: JSON.stringify({ chat_id: chatId }),
      });
      if (!r.ok || !r.body) return;

      const reader  = r.body.getReader();
      const decoder = new TextDecoder();
      let   buffer  = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim();
            if (data === '[DONE]') { onDone && onDone(); return; }
            try { onChunk && onChunk(JSON.parse(data)); } catch (_) {}
          }
        }
      }
      onDone && onDone();
    }

    /* Helpers: read from current page URL */
    getCurrentChatId() {
      const m = location.pathname.match(/\/chat\/([a-z0-9-]+)/i);
      return m ? m[1] : null;
    }

    getCurrentCharId() {
      const m = location.pathname.match(/\/character\/([a-z0-9-]+)/i);
      return m ? m[1] : null;
    }

    /* Hooks */
    hookBeforeSend(fn)    { _hooks.beforeSend.push(fn); }
    hookAfterReceive(fn)  { _hooks.afterReceive.push(fn); }

    /* System-prompt injection (stored in memory; applied via beforeSend hook) */
    _injections = {};

    injectSystemPrompt(id, text) {
      this._injections[id] = text;
      this._ensureInjectionHook();
    }

    removeInjection(id) { delete this._injections[id]; }

    _hookInstalled = false;
    _ensureInjectionHook() {
      if (this._hookInstalled) return;
      this._hookInstalled = true;
      this.hookBeforeSend((url, opts) => {
        if (!url.includes('/generateAlpha')) return;
        if (!Object.keys(this._injections).length) return;
        try {
          const body = JSON.parse(opts.body || '{}');
          const extra = Object.values(this._injections).join('\n\n');
          body.system_prompt_suffix = (body.system_prompt_suffix || '') + '\n\n' + extra;
          opts.body = JSON.stringify(body);
          return { url, opts };
        } catch (_) {}
      });
    }
  }

  /* ─── ADDON MANAGER ─────────────────────────────────────────────────────── */
  class AddonManager {
    constructor(api) {
      this._api      = api;
      this._registry = {};   // id → addon definition
      this._installed = Store.getObj('addons_installed', {});
      this._enabled   = Store.getObj('addons_enabled', {});
    }

    /** Register an addon definition (usually called by the addon itself) */
    register(addon) {
      this._validateAddon(addon);
      this._registry[addon.id] = addon;
      bus.emit('addon:registered', addon);
    }

    _validateAddon(addon) {
      const required = ['id', 'name', 'version', 'install'];
      for (const f of required) {
        if (!addon[f]) throw new Error(`Addon missing field: ${f}`);
      }
    }

    /** Install + activate an addon */
    async install(id, config = {}) {
      const addon = this._registry[id];
      if (!addon) throw new Error(`Addon not found: ${id}`);

      // Resolve dependencies first
      for (const dep of (addon.dependencies || [])) {
        if (!this._installed[dep]) await this.install(dep);
      }

      const mergedConfig = deepMerge(deepMerge({}, addon.defaultConfig || {}), config);
      this._installed[id] = { id, version: addon.version, config: mergedConfig };
      Store.setObj('addons_installed', this._installed);

      await this._activate(id);
    }

    async _activate(id) {
      const addon  = this._registry[id];
      const record = this._installed[id];
      if (!addon || !record) return;
      try {
        await addon.install(this._api, record.config, bus);
        this._enabled[id] = true;
        Store.setObj('addons_enabled', this._enabled);
        bus.emit('addon:enabled', id);
      } catch (e) {
        console.error(`[JSkid Addon:${id}] install() threw:`, e);
      }
    }

    async uninstall(id) {
      const addon = this._registry[id];
      if (addon && addon.uninstall) {
        try { await addon.uninstall(); } catch (_) {}
      }
      delete this._installed[id];
      delete this._enabled[id];
      Store.setObj('addons_installed', this._installed);
      Store.setObj('addons_enabled', this._enabled);
      bus.emit('addon:uninstalled', id);
    }

    async toggle(id) {
      if (this._enabled[id]) {
        const addon = this._registry[id];
        if (addon && addon.disable) try { await addon.disable(); } catch (_) {}
        delete this._enabled[id];
        Store.setObj('addons_enabled', this._enabled);
        bus.emit('addon:disabled', id);
      } else if (this._installed[id]) {
        await this._activate(id);
      }
    }

    /** Re-activate all previously-enabled addons on page load */
    async loadSaved() {
      for (const id of Object.keys(this._enabled)) {
        if (this._registry[id]) await this._activate(id).catch(() => {});
      }
    }

    list() {
      return Object.values(this._registry).map(a => ({
        ...a,
        installed: !!this._installed[a.id],
        enabled:   !!this._enabled[a.id],
        config:    this._installed[a.id]?.config || {},
      }));
    }

    getConfig(id) { return this._installed[id]?.config || {}; }
    setConfig(id, cfg) {
      if (this._installed[id]) {
        deepMerge(this._installed[id].config, cfg);
        Store.setObj('addons_installed', this._installed);
      }
    }
  }

  /* ─── TOOL SYSTEM ───────────────────────────────────────────────────────── */
  class ToolSystem {
    constructor(api) {
      this._api   = api;
      this._tools = {};     // id → tool definition
      this._active = {};    // chatId → Set of toolIds
    }

    register(tool) {
      if (!tool.id || !tool.name || !tool.execute) throw new Error('Tool missing id/name/execute');
      this._tools[tool.id] = tool;
      bus.emit('tool:registered', tool);
    }

    inject(chatId, toolId) {
      this._active[chatId] = this._active[chatId] || new Set();
      this._active[chatId].add(toolId);
      bus.emit('tool:injected', chatId, toolId);
    }

    eject(chatId, toolId) {
      this._active[chatId]?.delete(toolId);
      bus.emit('tool:ejected', chatId, toolId);
    }

    injectAll(toolId) {
      const chatId = this._api.getCurrentChatId();
      if (chatId) this.inject(chatId, toolId);
    }

    getActive(chatId) {
      return [...(this._active[chatId] || [])].map(id => this._tools[id]).filter(Boolean);
    }

    async execute(toolId, args, context) {
      const tool = this._tools[toolId];
      if (!tool) throw new Error(`Tool not found: ${toolId}`);
      return tool.execute(args, context, this._api);
    }

    list() { return Object.values(this._tools); }
  }

  /* ─── JSKRIPT INTERPRETER ───────────────────────────────────────────────── */
  class JSkriptInterpreter {
    constructor(api, tools) {
      this._api     = api;
      this._tools   = tools;
      this._scripts = Store.getObj('jskripts', {});  // id → { name, code }
      this._hooks   = {};  // event → [fn, ...]
    }

    _buildContext(extra = {}) {
      const self = this;
      return {
        // Event registration inside script
        onMessage:       fn => bus.on('message:received', fn),
        onGenerate:      fn => bus.on('generate:start', fn),
        onGenerateDone:  fn => bus.on('generate:done', fn),

        // API helpers
        sendMessage:     (content) => self._api.sendMessage(self._api.getCurrentChatId(), content),
        injectPrompt:    (id, text) => self._api.injectSystemPrompt(id, text),
        removePrompt:    (id) => self._api.removeInjection(id),
        useTool:         (id, args) => self._tools.execute(id, args, {}),

        // JSkid utilities
        log:   (...a) => console.log('[JSkript]', ...a),
        store: {
          get: k => Store.get('jskript_' + k),
          set: (k, v) => Store.set('jskript_' + k, v),
        },

        // Expose the raw API for power scripts
        api: self._api,

        ...extra,
      };
    }

    compile(id, name, code) {
      this._scripts[id] = { id, name, code };
      Store.setObj('jskripts', this._scripts);
      bus.emit('jskript:saved', id);
    }

    run(id, extra = {}) {
      const script = this._scripts[id];
      if (!script) throw new Error(`JSkript not found: ${id}`);
      const ctx  = this._buildContext(extra);
      const keys = Object.keys(ctx);
      const vals = Object.values(ctx);
      try {
        const fn = new Function(...keys, '"use strict";\n' + script.code); // eslint-disable-line no-new-func
        fn(...vals);
      } catch (e) {
        console.error(`[JSkript:${id}] Runtime error:`, e);
        throw e;
      }
    }

    delete(id) {
      delete this._scripts[id];
      Store.setObj('jskripts', this._scripts);
    }

    list() { return Object.values(this._scripts); }
  }

  /* ─── THEME MANAGER ─────────────────────────────────────────────────────── */
  const BUILT_IN_THEMES = {
    dark: {
      id: 'dark', name: 'Dark (Default)',
      vars: {
        '--jsk-bg':           '#0f0f0f',
        '--jsk-bg2':          '#1a1a1a',
        '--jsk-bg3':          '#252525',
        '--jsk-fg':           '#e8e8e8',
        '--jsk-fg2':          '#aaaaaa',
        '--jsk-accent':       '#7c6af7',
        '--jsk-accent2':      '#a08ef5',
        '--jsk-border':       '#2e2e2e',
        '--jsk-shadow':       'rgba(0,0,0,0.5)',
        '--jsk-radius':       '10px',
        '--jsk-font':         '"Inter", system-ui, sans-serif',
        '--jsk-mono':         '"JetBrains Mono", "Fira Code", monospace',
      },
    },
    ocean: {
      id: 'ocean', name: 'Ocean',
      vars: {
        '--jsk-bg':           '#0a1628',
        '--jsk-bg2':          '#0f2040',
        '--jsk-bg3':          '#1a3050',
        '--jsk-fg':           '#d0e8ff',
        '--jsk-fg2':          '#7ab0dd',
        '--jsk-accent':       '#00b4d8',
        '--jsk-accent2':      '#48cae4',
        '--jsk-border':       '#1a3a5c',
        '--jsk-shadow':       'rgba(0,20,50,0.6)',
        '--jsk-radius':       '8px',
        '--jsk-font':         '"Inter", system-ui, sans-serif',
        '--jsk-mono':         '"JetBrains Mono", monospace',
      },
    },
    neon: {
      id: 'neon', name: 'Neon Synthwave',
      vars: {
        '--jsk-bg':           '#0d0015',
        '--jsk-bg2':          '#160025',
        '--jsk-bg3':          '#1e003a',
        '--jsk-fg':           '#f0e0ff',
        '--jsk-fg2':          '#cc99ff',
        '--jsk-accent':       '#ff00ff',
        '--jsk-accent2':      '#00ffff',
        '--jsk-border':       '#3a005a',
        '--jsk-shadow':       'rgba(255,0,255,0.2)',
        '--jsk-radius':       '6px',
        '--jsk-font':         '"Rajdhani", "Inter", sans-serif',
        '--jsk-mono':         '"Share Tech Mono", monospace',
      },
    },
    rose: {
      id: 'rose', name: 'Rose Garden',
      vars: {
        '--jsk-bg':           '#1a0a10',
        '--jsk-bg2':          '#260f18',
        '--jsk-bg3':          '#341525',
        '--jsk-fg':           '#fde8ee',
        '--jsk-fg2':          '#dba0b8',
        '--jsk-accent':       '#e8618c',
        '--jsk-accent2':      '#f9a8c0',
        '--jsk-border':       '#4a1a2a',
        '--jsk-shadow':       'rgba(232,97,140,0.2)',
        '--jsk-radius':       '14px',
        '--jsk-font':         '"Lato", "Inter", sans-serif',
        '--jsk-mono':         '"JetBrains Mono", monospace',
      },
    },
    forest: {
      id: 'forest', name: 'Forest',
      vars: {
        '--jsk-bg':           '#0a1208',
        '--jsk-bg2':          '#101c0e',
        '--jsk-bg3':          '#182b14',
        '--jsk-fg':           '#d4efcf',
        '--jsk-fg2':          '#90c485',
        '--jsk-accent':       '#4caf50',
        '--jsk-accent2':      '#81c784',
        '--jsk-border':       '#1e3a1a',
        '--jsk-shadow':       'rgba(76,175,80,0.2)',
        '--jsk-radius':       '8px',
        '--jsk-font':         '"Inter", sans-serif',
        '--jsk-mono':         '"JetBrains Mono", monospace',
      },
    },
    light: {
      id: 'light', name: 'Light',
      vars: {
        '--jsk-bg':           '#f5f5f5',
        '--jsk-bg2':          '#ffffff',
        '--jsk-bg3':          '#ebebeb',
        '--jsk-fg':           '#1a1a1a',
        '--jsk-fg2':          '#555555',
        '--jsk-accent':       '#6c63ff',
        '--jsk-accent2':      '#9c96ff',
        '--jsk-border':       '#dddddd',
        '--jsk-shadow':       'rgba(0,0,0,0.1)',
        '--jsk-radius':       '10px',
        '--jsk-font':         '"Inter", sans-serif',
        '--jsk-mono':         '"JetBrains Mono", monospace',
      },
    },
  };

  class ThemeManager {
    constructor() {
      this._styleEl  = null;
      this._wallEl   = null;
      this._animFrame = null;
      this._current  = Store.get('theme_id', 'dark');
      this._custom   = Store.getObj('theme_custom', {});
    }

    _varCSS(vars) {
      return ':root{' + Object.entries(vars).map(([k, v]) => `${k}:${v}`).join(';') + '}';
    }

    apply(themeId) {
      const theme = BUILT_IN_THEMES[themeId] || BUILT_IN_THEMES.dark;
      this._current = themeId;
      Store.set('theme_id', themeId);
      if (!this._styleEl) {
        this._styleEl = document.createElement('style');
        this._styleEl.id = 'jskid-theme';
        document.head.appendChild(this._styleEl);
      }
      this._styleEl.textContent = this._varCSS(theme.vars);
      bus.emit('theme:applied', themeId);
    }

    applyCustom(vars) {
      deepMerge(this._custom, vars);
      Store.setObj('theme_custom', this._custom);
      if (!this._styleEl) { this._styleEl = document.createElement('style'); document.head.appendChild(this._styleEl); }
      this._styleEl.textContent += ':root{' + Object.entries(this._custom).map(([k, v]) => `${k}:${v}`).join(';') + '}';
    }

    setWallpaper(url, blur = 0, opacity = 0.15) {
      this._removeWallpaper();
      this._wallEl = el('div', {
        id: 'jskid-wallpaper',
        style: {
          position: 'fixed', inset: '0', zIndex: '-1', pointerEvents: 'none',
          background: `url("${url}") center/cover no-repeat`,
          opacity: String(opacity),
          filter: blur ? `blur(${blur}px)` : '',
        },
      });
      document.body.prepend(this._wallEl);
    }

    setAnimatedWallpaper(type) {
      this._removeWallpaper();
      const canvas = el('canvas', { id: 'jskid-wallpaper-canvas', style: { position: 'fixed', inset: '0', zIndex: '-1', pointerEvents: 'none', opacity: '0.25' } });
      document.body.prepend(canvas);
      canvas.width  = window.innerWidth;
      canvas.height = window.innerHeight;
      this._wallEl  = canvas;
      this._startAnimation(canvas, type);
    }

    _startAnimation(canvas, type) {
      const ctx = canvas.getContext('2d');
      if (type === 'matrix') this._animMatrix(canvas, ctx);
      else if (type === 'stars') this._animStars(canvas, ctx);
      else if (type === 'particles') this._animParticles(canvas, ctx);
      else if (type === 'waves') this._animWaves(canvas, ctx);
    }

    _animMatrix(canvas, ctx) {
      const cols = Math.floor(canvas.width / 16);
      const drops = Array(cols).fill(0);
      const chars = 'アイウエオカキクケコサシスセソJSKID01'.split('');
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--jsk-accent').trim() || '#7c6af7';
      const loop = () => {
        ctx.fillStyle = 'rgba(0,0,0,0.05)';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = accent;
        ctx.font = '14px monospace';
        for (let i = 0; i < drops.length; i++) {
          ctx.fillText(chars[Math.floor(Math.random() * chars.length)], i * 16, drops[i] * 16);
          if (drops[i] * 16 > canvas.height && Math.random() > 0.975) drops[i] = 0;
          drops[i]++;
        }
        this._animFrame = requestAnimationFrame(loop);
      };
      loop();
    }

    _animStars(canvas, ctx) {
      const stars = Array.from({ length: 200 }, () => ({
        x: Math.random() * canvas.width,
        y: Math.random() * canvas.height,
        r: Math.random() * 1.5 + 0.2,
        s: Math.random() * 0.4 + 0.1,
      }));
      const loop = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#ffffff';
        for (const s of stars) {
          s.x -= s.s;
          if (s.x < 0) { s.x = canvas.width; s.y = Math.random() * canvas.height; }
          ctx.beginPath();
          ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2);
          ctx.fill();
        }
        this._animFrame = requestAnimationFrame(loop);
      };
      loop();
    }

    _animParticles(canvas, ctx) {
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--jsk-accent').trim() || '#7c6af7';
      const pts = Array.from({ length: 80 }, () => ({
        x: Math.random() * canvas.width, y: Math.random() * canvas.height,
        vx: (Math.random() - 0.5) * 0.8, vy: (Math.random() - 0.5) * 0.8,
        r: Math.random() * 3 + 1,
      }));
      const loop = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (const p of pts) {
          p.x += p.vx; p.y += p.vy;
          if (p.x < 0 || p.x > canvas.width)  p.vx *= -1;
          if (p.y < 0 || p.y > canvas.height) p.vy *= -1;
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
          ctx.fillStyle = accent;
          ctx.fill();
          // connect nearby
          for (const q of pts) {
            const d = Math.hypot(p.x - q.x, p.y - q.y);
            if (d < 100) {
              ctx.beginPath();
              ctx.moveTo(p.x, p.y);
              ctx.lineTo(q.x, q.y);
              ctx.strokeStyle = accent + Math.floor((1 - d / 100) * 60).toString(16).padStart(2, '0');
              ctx.lineWidth = 0.5;
              ctx.stroke();
            }
          }
        }
        this._animFrame = requestAnimationFrame(loop);
      };
      loop();
    }

    _animWaves(canvas, ctx) {
      let t = 0;
      const accent = getComputedStyle(document.documentElement).getPropertyValue('--jsk-accent').trim() || '#7c6af7';
      const loop = () => {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        for (let w = 0; w < 3; w++) {
          ctx.beginPath();
          for (let x = 0; x <= canvas.width; x += 4) {
            const y = canvas.height / 2 + Math.sin((x / 200) + t + w) * (40 + w * 20);
            x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          }
          ctx.strokeStyle = accent + ['40', '30', '20'][w];
          ctx.lineWidth = 2;
          ctx.stroke();
        }
        t += 0.02;
        this._animFrame = requestAnimationFrame(loop);
      };
      loop();
    }

    _removeWallpaper() {
      if (this._animFrame) { cancelAnimationFrame(this._animFrame); this._animFrame = null; }
      document.getElementById('jskid-wallpaper')?.remove();
      document.getElementById('jskid-wallpaper-canvas')?.remove();
      this._wallEl = null;
    }

    removeWallpaper() { this._removeWallpaper(); Store.del('wallpaper'); }

    init() { this.apply(this._current); }
    getCurrent() { return this._current; }
    list() { return Object.values(BUILT_IN_THEMES); }
  }

  /* ─── TWEAKS MANAGER ────────────────────────────────────────────────────── */
  const TWEAKS_DEFS = [
    /* ── Layout ── */
    { id: 'chat_width',       cat: 'Layout',    type: 'range',   label: 'Chat max-width (px)',       default: 800,   min: 400, max: 1600, step: 50,
      apply: v => GM.addStyle(`.messages-container,.chat-container{max-width:${v}px!important;margin:0 auto}`) },
    { id: 'sidebar_hidden',   cat: 'Layout',    type: 'toggle',  label: 'Hide sidebar by default',   default: false,
      apply: v => v && GM.addStyle('.sidebar,.left-panel{display:none!important}') },
    { id: 'compact_messages', cat: 'Layout',    type: 'toggle',  label: 'Compact message spacing',   default: false,
      apply: v => v && GM.addStyle('.message,.chat-message{padding:6px 10px!important;margin:2px 0!important}') },
    { id: 'hide_avatars',     cat: 'Layout',    type: 'toggle',  label: 'Hide character avatars',     default: false,
      apply: v => v && GM.addStyle('.avatar,.char-avatar{display:none!important}') },
    { id: 'full_width_input', cat: 'Layout',    type: 'toggle',  label: 'Full-width message input',  default: true,
      apply: v => v && GM.addStyle('textarea,input[type=text]{width:100%!important;box-sizing:border-box}') },
    { id: 'floating_input',   cat: 'Layout',    type: 'toggle',  label: 'Floating bottom input bar', default: false,
      apply: v => v && GM.addStyle('.input-area,.chat-input-area{position:sticky!important;bottom:0!important;background:var(--jsk-bg2)!important;z-index:10!important}') },

    /* ── Typography ── */
    { id: 'font_size',        cat: 'Typography', type: 'range',  label: 'Font size (px)',            default: 16,  min: 12, max: 24, step: 1,
      apply: v => GM.addStyle(`body{font-size:${v}px!important}`) },
    { id: 'line_height',      cat: 'Typography', type: 'range',  label: 'Line height',               default: 1.6, min: 1.2, max: 2.5, step: 0.1,
      apply: v => GM.addStyle(`body{line-height:${v}!important}`) },
    { id: 'monospace_chat',   cat: 'Typography', type: 'toggle', label: 'Monospace chat font',       default: false,
      apply: v => v && GM.addStyle('.message,.chat-message{font-family:var(--jsk-mono)!important}') },
    { id: 'italic_ai',        cat: 'Typography', type: 'toggle', label: 'Italicise AI messages',     default: false,
      apply: v => v && GM.addStyle('.ai-message .message-content,.char-message .content{font-style:italic!important}') },
    { id: 'bold_user',        cat: 'Typography', type: 'toggle', label: 'Bold user messages',        default: false,
      apply: v => v && GM.addStyle('.user-message .message-content,.user-msg .content{font-weight:600!important}') },

    /* ── Message Bubbles ── */
    { id: 'bubble_radius',    cat: 'Bubbles',   type: 'range',   label: 'Bubble border radius (px)', default: 10, min: 0, max: 30, step: 1,
      apply: v => GM.addStyle(`.message,.chat-bubble,.chat-message{border-radius:${v}px!important}`) },
    { id: 'user_bubble_color',cat: 'Bubbles',   type: 'color',   label: 'User bubble color',         default: '#1e1e2e',
      apply: v => GM.addStyle(`.user-message,.user-msg{background:${v}!important}`) },
    { id: 'ai_bubble_color',  cat: 'Bubbles',   type: 'color',   label: 'AI bubble color',           default: '#131323',
      apply: v => GM.addStyle(`.ai-message,.char-message{background:${v}!important}`) },
    { id: 'bubble_shadow',    cat: 'Bubbles',   type: 'toggle',  label: 'Bubble drop shadow',        default: false,
      apply: v => v && GM.addStyle('.message,.chat-bubble{box-shadow:0 2px 8px var(--jsk-shadow)!important}') },
    { id: 'show_timestamps',  cat: 'Bubbles',   type: 'toggle',  label: 'Show message timestamps',   default: true,
      apply: v => {
        if (v) {
          const style = GM.addStyle('.jskid-timestamp{font-size:10px;opacity:0.5;margin-top:2px;display:block}');
          // inject timestamps via MutationObserver
          _observeMessages(el => {
            if (!el.querySelector('.jskid-timestamp')) {
              const ts = document.createElement('span');
              ts.className = 'jskid-timestamp';
              ts.textContent = new Date().toLocaleTimeString();
              el.appendChild(ts);
            }
          });
        }
      }
    },
    { id: 'word_count',       cat: 'Bubbles',   type: 'toggle',  label: 'Show word count on hover',  default: false,
      apply: v => v && GM.addStyle('.message:hover::after,.chat-message:hover::after{content:attr(data-wc)" words";position:absolute;top:-20px;right:0;font-size:10px;background:var(--jsk-bg3);padding:2px 6px;border-radius:4px}') },

    /* ── Behaviour ── */
    { id: 'auto_scroll',      cat: 'Behaviour', type: 'toggle',  label: 'Auto-scroll to new messages', default: true,
      apply: v => v && _watchAutoScroll() },
    { id: 'send_on_enter',    cat: 'Behaviour', type: 'toggle',  label: 'Send on Enter (no shift)',  default: true,
      apply: v => {
        document.addEventListener('keydown', e => {
          if (e.key === 'Enter' && !e.shiftKey && v) {
            const btn = $('[data-testid="send-button"],button.send-btn,button[type="submit"]');
            if (btn && document.activeElement?.matches('textarea')) { e.preventDefault(); btn.click(); }
          }
        }, true);
      }
    },
    { id: 'double_click_edit',cat: 'Behaviour', type: 'toggle',  label: 'Double-click message to edit', default: true,
      apply: v => v && _enableDoubleClickEdit() },
    { id: 'auto_save_draft',  cat: 'Behaviour', type: 'toggle',  label: 'Auto-save input draft',     default: true,
      apply: v => v && _enableDraftSave() },
    { id: 'confirm_delete',   cat: 'Behaviour', type: 'toggle',  label: 'Confirm before deleting',   default: true,
      apply: () => {} },  // handled in delete intercept
    { id: 'auto_retry',       cat: 'Behaviour', type: 'toggle',  label: 'Auto-retry on generation error', default: false,
      apply: v => v && _hookAutoRetry() },

    /* ── Notifications ── */
    { id: 'sound_notify',     cat: 'Notifications', type: 'toggle', label: 'Sound on AI response',   default: false,
      apply: v => v && bus.on('generate:done', () => _playBeep()) },
    { id: 'desktop_notify',   cat: 'Notifications', type: 'toggle', label: 'Desktop notification on AI response', default: false,
      apply: v => v && _requestNotifyPerms() },

    /* ── Appearance misc ── */
    { id: 'hide_ads',         cat: 'Appearance', type: 'toggle', label: 'Hide ads / promoted content', default: true,
      apply: v => v && GM.addStyle('.ad,.promoted,.sponsored,.advertisement{display:none!important}') },
    { id: 'hide_rating',      cat: 'Appearance', type: 'toggle', label: 'Hide rating buttons',       default: false,
      apply: v => v && GM.addStyle('.rating-buttons,.thumbs-container{display:none!important}') },
    { id: 'blur_nsfw',        cat: 'Appearance', type: 'toggle', label: 'Blur NSFW images',          default: false,
      apply: v => v && GM.addStyle('[data-nsfw="true"] img,.nsfw-image{filter:blur(16px)!important;transition:filter 0.2s} [data-nsfw="true"] img:hover,.nsfw-image:hover{filter:none!important}') },
    { id: 'hide_header',      cat: 'Appearance', type: 'toggle', label: 'Hide top header bar',       default: false,
      apply: v => v && GM.addStyle('header,nav.main-nav,.top-bar{display:none!important}') },
    { id: 'reduce_motion',    cat: 'Appearance', type: 'toggle', label: 'Reduce animations',         default: false,
      apply: v => v && GM.addStyle('*{animation-duration:0.01ms!important;transition-duration:0.1ms!important}') },
    { id: 'show_char_stats',  cat: 'Appearance', type: 'toggle', label: 'Show input character count', default: true,
      apply: v => v && _showCharCount() },
    { id: 'markdown_preview', cat: 'Appearance', type: 'toggle', label: 'Live markdown preview in input', default: false,
      apply: v => v && _enableMarkdownPreview() },
    { id: 'rainbow_border',   cat: 'Appearance', type: 'toggle', label: 'Rainbow animated border',   default: false,
      apply: v => v && GM.addStyle('@keyframes jsk-rainbow{0%{border-color:#ff0000}16%{border-color:#ff8800}33%{border-color:#ffff00}50%{border-color:#00ff00}66%{border-color:#0088ff}83%{border-color:#8800ff}100%{border-color:#ff0000}}.message:hover{border:1px solid;animation:jsk-rainbow 2s linear infinite!important}') },
    { id: 'glass_ui',         cat: 'Appearance', type: 'toggle', label: 'Glassmorphism UI panels',   default: false,
      apply: v => v && GM.addStyle('.card,.panel,.modal,.sidebar{background:rgba(255,255,255,0.05)!important;backdrop-filter:blur(12px)!important;border:1px solid rgba(255,255,255,0.1)!important}') },

    /* ── Privacy ── */
    { id: 'block_analytics',  cat: 'Privacy',   type: 'toggle',  label: 'Block analytics tracking', default: true,
      apply: v => v && _blockAnalytics() },
    { id: 'no_typing_indicator', cat: 'Privacy', type: 'toggle', label: 'Disable typing indicator', default: false,
      apply: () => {} },

    /* ── Power ── */
    { id: 'custom_css',       cat: 'Power',     type: 'textarea', label: 'Custom CSS injection',    default: '',
      apply: v => v && GM.addStyle(v) },
  ];

  // Helper functions used by tweaks
  function _observeMessages(cb) {
    const obs = new MutationObserver(muts => {
      for (const mut of muts) {
        for (const node of mut.addedNodes) {
          if (node.nodeType === 1 && node.matches?.('.message,.chat-message')) cb(node);
        }
      }
    });
    obs.observe(document.body, { childList: true, subtree: true });
  }

  function _watchAutoScroll() {
    bus.on('generate:done', () => {
      const last = $$('.message,.chat-message').at(-1);
      last?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    });
  }

  function _enableDoubleClickEdit() {
    document.addEventListener('dblclick', e => {
      const msg = e.target.closest('.user-message,.user-msg');
      if (!msg) return;
      const content = msg.querySelector('.message-content,.content');
      if (!content) return;
      const original = content.textContent;
      content.contentEditable = 'true';
      content.focus();
      const save = () => {
        content.contentEditable = 'false';
        const chatId = jskid.api.getCurrentChatId();
        const msgId  = msg.dataset.messageId || msg.dataset.id;
        if (chatId && msgId && content.textContent !== original) {
          jskid.api.editMessage(chatId, msgId, content.textContent);
        }
      };
      content.addEventListener('blur', save, { once: true });
      content.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); content.blur(); } });
    });
  }

  function _enableDraftSave() {
    const save = debounce(v => Store.set('draft_' + location.pathname, v), 500);
    document.addEventListener('input', e => {
      if (e.target.matches('textarea')) save(e.target.value);
    });
    // restore
    setTimeout(() => {
      const ta = $('textarea');
      if (ta) {
        const saved = Store.get('draft_' + location.pathname, '');
        if (saved) ta.value = saved;
      }
    }, 1500);
  }

  function _hookAutoRetry() {
    let retries = 0;
    bus.on('generate:error', () => {
      if (retries < 3) {
        retries++;
        setTimeout(() => {
          const btn = $('[data-testid="regenerate"],button.regenerate-btn,.regen-btn');
          btn?.click();
        }, 2000);
      } else {
        retries = 0;
      }
    });
  }

  function _playBeep() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      gain.gain.setValueAtTime(0.1, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
      osc.start(); osc.stop(ctx.currentTime + 0.3);
    } catch (_) {}
  }

  function _requestNotifyPerms() {
    if (typeof Notification !== 'undefined') {
      Notification.requestPermission().then(p => {
        if (p === 'granted') {
          bus.on('generate:done', () => {
            if (document.hidden) {
              new Notification('JanitorAI', { body: 'AI has responded!', icon: '/favicon.ico' });
            }
          });
        }
      });
    }
  }

  function _blockAnalytics() {
    _hooks.beforeSend.push((url) => {
      if (url.includes('/jstats/') || url.includes('statsig') || url.includes('analytics') || url.includes('telemetry')) {
        return new Promise(() => {}); // hang forever = block
      }
    });
  }

  function _showCharCount() {
    document.addEventListener('input', e => {
      if (!e.target.matches('textarea')) return;
      let counter = e.target.parentElement.querySelector('.jskid-charcount');
      if (!counter) {
        counter = el('div', { style: { fontSize: '11px', opacity: '0.5', textAlign: 'right', marginTop: '2px' } });
        counter.className = 'jskid-charcount';
        e.target.parentElement.appendChild(counter);
      }
      counter.textContent = e.target.value.length + ' chars';
    });
  }

  function _enableMarkdownPreview() {
    // Simple markdown → text visual hints (bold, italic, code)
    GM.addStyle(`
      .jskid-md-preview{padding:8px;background:var(--jsk-bg3);border-radius:6px;font-size:13px;margin-top:4px;border:1px solid var(--jsk-border)}
      .jskid-md-preview b{color:var(--jsk-accent)}
    `);
  }

  class TweaksManager {
    constructor() {
      this._state = Store.getObj('tweaks', {});
    }

    init() {
      for (const def of TWEAKS_DEFS) {
        const val = this._state[def.id] !== undefined ? this._state[def.id] : def.default;
        try { def.apply(val); } catch (e) { console.warn('[JSkid Tweak]', def.id, e); }
      }
    }

    get(id) {
      const def = TWEAKS_DEFS.find(d => d.id === id);
      return this._state[id] !== undefined ? this._state[id] : def?.default;
    }

    set(id, value) {
      this._state[id] = value;
      Store.setObj('tweaks', this._state);
      const def = TWEAKS_DEFS.find(d => d.id === id);
      try { def?.apply(value); } catch (e) { console.warn('[JSkid Tweak apply]', id, e); }
      bus.emit('tweak:changed', id, value);
    }

    list() { return TWEAKS_DEFS; }
    categories() { return [...new Set(TWEAKS_DEFS.map(d => d.cat))]; }
  }

  /* ─── DESIGN SYSTEM ─────────────────────────────────────────────────────── */
  const DESIGNS = {
    default: {
      id: 'default', name: 'Default', icon: '🏠',
      description: 'JanitorAI as-is, with JSkid enhancements only',
      apply() { _removeAllDesigns(); },
    },
    minimal: {
      id: 'minimal', name: 'Minimal', icon: '◻️',
      description: 'Clean, distraction-free reading experience',
      apply() {
        _removeAllDesigns();
        GM.addStyle(`
          header,nav,.sidebar,.left-panel,.top-bar,.footer-nav{display:none!important}
          body{background:var(--jsk-bg)!important}
          .main-content,.chat-area{max-width:720px!important;margin:40px auto!important;padding:0 20px!important}
        `);
      },
    },
    terminal: {
      id: 'terminal', name: 'Terminal', icon: '⌨️',
      description: 'Monospace terminal-like interface',
      apply() {
        _removeAllDesigns();
        GM.addStyle(`
          *{font-family:var(--jsk-mono)!important;letter-spacing:0.02em}
          body{background:#000!important;color:#00ff00!important}
          :root{--jsk-bg:#000;--jsk-bg2:#0a0a0a;--jsk-bg3:#111;--jsk-fg:#00ff00;--jsk-fg2:#00aa00;--jsk-accent:#00ff00;--jsk-border:#00440044}
          .message,.chat-message,.chat-bubble{background:#0a0a0a!important;border:1px solid #00440044!important;border-radius:0!important}
          .message::before{content:"> ";color:#00ff00}
          header,nav,.sidebar,.top-bar{background:#000!important;border-bottom:1px solid #00440044!important}
          button,input,textarea{background:#000!important;color:#00ff00!important;border:1px solid #00880088!important;border-radius:0!important}
        `);
      },
    },
    floating: {
      id: 'floating', name: 'Floating Windows', icon: '🪟',
      description: 'Detachable floating panel layout',
      apply() {
        _removeAllDesigns();
        GM.addStyle(`
          body{background:var(--jsk-bg)!important;overflow:hidden}
          .chat-area,.main-chat{
            position:fixed!important;top:60px!important;left:60px!important;
            width:calc(100vw - 120px)!important;height:calc(100vh - 120px)!important;
            background:var(--jsk-bg2)!important;border-radius:12px!important;
            border:1px solid var(--jsk-border)!important;overflow:auto!important;
            box-shadow:0 8px 40px var(--jsk-shadow)!important;
          }
          .sidebar,.left-panel{
            position:fixed!important;left:0!important;top:0!important;bottom:0!important;
            width:50px!important;overflow:hidden!important;transition:width 0.2s!important;
            background:var(--jsk-bg3)!important;z-index:100!important;
          }
          .sidebar:hover,.left-panel:hover{width:260px!important}
        `);
        _injectTaskbar();
      },
    },
    cozy: {
      id: 'cozy', name: 'Cozy', icon: '🛋️',
      description: 'Warm, rounded, comfortable reading',
      apply() {
        _removeAllDesigns();
        GM.addStyle(`
          :root{--jsk-radius:18px}
          body{background:var(--jsk-bg)!important;font-size:17px!important;line-height:1.8!important}
          .message,.chat-message,.chat-bubble{
            border-radius:18px!important;padding:14px 20px!important;
            margin:10px 0!important;box-shadow:0 2px 12px var(--jsk-shadow)!important;
          }
          .user-message,.user-msg{border-radius:18px 18px 4px 18px!important}
          .ai-message,.char-message{border-radius:18px 18px 18px 4px!important}
          input,textarea,button{border-radius:14px!important}
          header,.top-bar{border-radius:0 0 16px 16px!important}
        `);
      },
    },
    dock: {
      id: 'dock', name: 'Dock + Desktop', icon: '🖥️',
      description: 'macOS-style dock with desktop background',
      apply() {
        _removeAllDesigns();
        GM.addStyle(`
          body{background:var(--jsk-bg)!important;padding-bottom:80px!important}
          header,.top-bar,.sidebar{display:none!important}
          .main-content,.chat-area{max-width:800px!important;margin:20px auto!important}
        `);
        _injectDock();
      },
    },
  };

  const _designStyles = [];
  function _removeAllDesigns() {
    for (const s of _designStyles) s.remove();
    _designStyles.length = 0;
    document.getElementById('jskid-taskbar')?.remove();
    document.getElementById('jskid-dock')?.remove();
  }

  function _injectTaskbar() {
    const bar = el('div', { id: 'jskid-taskbar', style: { position: 'fixed', bottom: '0', left: '0', right: '0', height: '40px', background: 'var(--jsk-bg3)', borderTop: '1px solid var(--jsk-border)', display: 'flex', alignItems: 'center', padding: '0 12px', gap: '8px', zIndex: '9999' } },
      el('span', { style: { fontSize: '12px', color: 'var(--jsk-fg2)' } }, '🪟 JSkid Desktop'),
    );
    document.body.appendChild(bar);
  }

  function _injectDock() {
    const dock = el('div', { id: 'jskid-dock', style: { position: 'fixed', bottom: '12px', left: '50%', transform: 'translateX(-50%)', background: 'rgba(255,255,255,0.08)', backdropFilter: 'blur(20px)', border: '1px solid var(--jsk-border)', borderRadius: '20px', padding: '8px 16px', display: 'flex', gap: '12px', zIndex: '9999' } },
      ...['🏠','💬','👤','⚙️','🔍'].map(icon =>
        el('button', { style: { background: 'none', border: 'none', fontSize: '22px', cursor: 'pointer', padding: '4px 8px', borderRadius: '10px', transition: 'transform 0.15s' }, onMouseenter: e => e.target.style.transform = 'scale(1.4)', onMouseleave: e => e.target.style.transform = '' }, icon),
      ),
    );
    document.body.appendChild(dock);
  }

  class DesignManager {
    constructor() {
      this._current = Store.get('design_id', 'default');
    }

    apply(id) {
      const design = DESIGNS[id];
      if (!design) return;
      design.apply();
      this._current = id;
      Store.set('design_id', id);
      bus.emit('design:applied', id);
    }

    list()       { return Object.values(DESIGNS); }
    getCurrent() { return this._current; }
    init()       { this.apply(this._current); }
  }

  /* ─── UI MANAGER (bubble + menu) ────────────────────────────────────────── */
  class UIManager {
    constructor(jskidRef) {
      this._j      = jskidRef;
      this._root   = null;
      this._shadow = null;
      this._panel  = null;
      this._activeTab = 'addons';
    }

    init() {
      this._injectBaseCSS();
      this._createBubble();
    }

    _injectBaseCSS() {
      GM.addStyle(`
        #jskid-bubble{
          position:fixed;bottom:24px;right:24px;z-index:2147483647;
          width:48px;height:48px;border-radius:50%;
          background:var(--jsk-accent,#7c6af7);color:#fff;
          font-size:22px;border:none;cursor:pointer;
          box-shadow:0 4px 20px rgba(0,0,0,0.4);
          transition:transform 0.2s,box-shadow 0.2s;
          display:flex;align-items:center;justify-content:center;
          user-select:none;
        }
        #jskid-bubble:hover{transform:scale(1.12);box-shadow:0 6px 28px rgba(0,0,0,0.5)}
        #jskid-bubble.open{transform:rotate(45deg) scale(1.1)}
      `);
    }

    _createBubble() {
      const bubble = el('button', { id: 'jskid-bubble', title: 'JSkid Menu' }, '✦');
      bubble.addEventListener('click', () => this._togglePanel());
      document.body.appendChild(bubble);
    }

    _togglePanel() {
      if (this._panel) { this._closePanel(); return; }
      this._openPanel();
      document.getElementById('jskid-bubble').classList.add('open');
    }

    _openPanel() {
      const panel = this._buildPanel();
      document.body.appendChild(panel);
      this._panel = panel;
      requestAnimationFrame(() => panel.style.opacity = '1');
    }

    _closePanel() {
      this._panel?.remove();
      this._panel = null;
      document.getElementById('jskid-bubble')?.classList.remove('open');
    }

    _buildPanel() {
      const panel = el('div', {
        id: 'jskid-panel',
        style: {
          position:   'fixed', bottom: '82px', right: '24px',
          width:      '480px', maxHeight: '80vh',
          background: 'var(--jsk-bg2,#1a1a1a)',
          border:     '1px solid var(--jsk-border,#2e2e2e)',
          borderRadius: 'var(--jsk-radius,10px)',
          boxShadow:  '0 8px 40px rgba(0,0,0,0.6)',
          color:      'var(--jsk-fg,#e8e8e8)',
          fontFamily: 'var(--jsk-font,system-ui)',
          fontSize:   '13px',
          display:    'flex', flexDirection: 'column',
          zIndex:     '2147483646',
          opacity:    '0', transition: 'opacity 0.15s',
          overflow:   'hidden',
        },
      });

      panel.appendChild(this._buildPanelHeader());
      panel.appendChild(this._buildTabBar());
      const body = el('div', { style: { flex: '1', overflowY: 'auto', padding: '16px' } });
      body.appendChild(this._renderTab(this._activeTab));
      panel.appendChild(body);

      // Tab click
      panel.querySelectorAll('.jskid-tab').forEach(t => {
        t.addEventListener('click', () => {
          this._activeTab = t.dataset.tab;
          panel.querySelectorAll('.jskid-tab').forEach(x => x.classList.remove('active'));
          t.classList.add('active');
          body.innerHTML = '';
          body.appendChild(this._renderTab(this._activeTab));
        });
      });

      // Close on outside click
      setTimeout(() => {
        document.addEventListener('click', e => {
          if (this._panel && !this._panel.contains(e.target) && e.target.id !== 'jskid-bubble') {
            this._closePanel();
          }
        }, { once: true });
      }, 100);

      return panel;
    }

    _buildPanelHeader() {
      return el('div', { style: { padding: '12px 16px', borderBottom: '1px solid var(--jsk-border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' } },
        el('span', { style: { fontWeight: '700', fontSize: '15px', letterSpacing: '0.05em' } }, '✦ JSkid v' + VERSION),
        el('button', { style: { background: 'none', border: 'none', color: 'var(--jsk-fg2)', cursor: 'pointer', fontSize: '18px', lineHeight: '1' }, onClick: () => this._closePanel() }, '×'),
      );
    }

    _buildTabBar() {
      const tabs = [
        { id: 'addons',   label: '🧩 Addons' },
        { id: 'tools',    label: '🛠️ Tools' },
        { id: 'jskript',  label: '✏️ JSkript' },
        { id: 'themes',   label: '🎨 Themes' },
        { id: 'tweaks',   label: '⚙️ Tweaks' },
        { id: 'designs',  label: '🖼️ Designs' },
        { id: 'changelog',label: '📋 Changes' },
      ];
      const bar = el('div', { style: { display: 'flex', borderBottom: '1px solid var(--jsk-border)', overflowX: 'auto', flexShrink: '0' } });
      for (const t of tabs) {
        const btn = el('button', {
          'data-tab': t.id,
          class: 'jskid-tab' + (t.id === this._activeTab ? ' active' : ''),
          style: {
            flex: '0 0 auto', padding: '10px 14px', background: 'none', border: 'none',
            borderBottom: t.id === this._activeTab ? '2px solid var(--jsk-accent)' : '2px solid transparent',
            color: t.id === this._activeTab ? 'var(--jsk-accent)' : 'var(--jsk-fg2)',
            cursor: 'pointer', fontSize: '12px', whiteSpace: 'nowrap', transition: 'color 0.15s',
          },
        }, t.label);
        bar.appendChild(btn);
      }
      return bar;
    }

    _renderTab(tab) {
      const fns = {
        addons:    () => this._renderAddons(),
        tools:     () => this._renderTools(),
        jskript:   () => this._renderJSkript(),
        themes:    () => this._renderThemes(),
        tweaks:    () => this._renderTweaks(),
        designs:   () => this._renderDesigns(),
        changelog: () => this._renderChangelog(),
      };
      return (fns[tab] || fns.addons)();
    }

    /* ── Addons tab ── */
    _renderAddons() {
      const div = el('div');
      const addons = this._j.addons.list();

      if (!addons.length) {
        div.appendChild(el('p', { style: { color: 'var(--jsk-fg2)', textAlign: 'center', marginTop: '24px' } }, 'No addons registered yet. Addons self-register by calling JSkid.addons.register(def).'));
        return div;
      }

      for (const a of addons) {
        const card = el('div', { style: { background: 'var(--jsk-bg3)', borderRadius: '8px', padding: '12px', marginBottom: '10px', border: '1px solid var(--jsk-border)' } },
          el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' } },
            el('div', {},
              el('strong', {}, a.name),
              el('span', { style: { marginLeft: '8px', color: 'var(--jsk-fg2)', fontSize: '11px' } }, 'v' + a.version),
              el('br'),
              el('small', { style: { color: 'var(--jsk-fg2)' } }, a.description || ''),
            ),
            el('div', { style: { display: 'flex', gap: '6px', flexShrink: '0' } },
              ...(a.installed ? [
                this._toggleBtn(a.enabled, () => this._j.addons.toggle(a.id).then(() => this._refreshTab())),
                el('button', this._btnStyle('danger'), 'Remove', { onClick: () => this._j.addons.uninstall(a.id).then(() => this._refreshTab()) }),
              ] : [
                el('button', this._btnStyle('primary'), 'Install', { onClick: () => this._j.addons.install(a.id).then(() => this._refreshTab()) }),
              ]),
            ),
          ),
          ...(a.dependencies?.length ? [el('small', { style: { color: 'var(--jsk-fg2)' } }, 'Requires: ' + a.dependencies.join(', '))] : []),
        );
        div.appendChild(card);
      }
      return div;
    }

    /* ── Tools tab ── */
    _renderTools() {
      const div = el('div');
      const tools = this._j.tools.list();

      if (!tools.length) {
        div.appendChild(el('p', { style: { color: 'var(--jsk-fg2)', textAlign: 'center', marginTop: '24px' } }, 'No tools registered. Addons and JSkripts can register tools via JSkid.tools.register(def).'));
        return div;
      }

      for (const t of tools) {
        const chatId = this._j.api.getCurrentChatId();
        const active = chatId && this._j.tools.getActive(chatId).some(x => x.id === t.id);
        div.appendChild(el('div', { style: { background: 'var(--jsk-bg3)', borderRadius: '8px', padding: '12px', marginBottom: '8px', border: '1px solid var(--jsk-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
          el('div', {},
            el('strong', {}, t.name),
            el('br'),
            el('small', { style: { color: 'var(--jsk-fg2)' } }, t.description || ''),
          ),
          this._toggleBtn(active, () => {
            if (chatId) { active ? this._j.tools.eject(chatId, t.id) : this._j.tools.inject(chatId, t.id); this._refreshTab(); }
          }),
        ));
      }
      return div;
    }

    /* ── JSkript tab ── */
    _renderJSkript() {
      const div = el('div');
      const scripts = this._j.jskript.list();

      // New script button
      div.appendChild(el('button', { ...this._btnStyle('primary'), style: { ...this._btnStyle('primary').style, marginBottom: '12px' }, onClick: () => this._showScriptEditor() }, '+ New Script'));

      for (const s of scripts) {
        div.appendChild(el('div', { style: { background: 'var(--jsk-bg3)', borderRadius: '8px', padding: '10px 12px', marginBottom: '8px', border: '1px solid var(--jsk-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' } },
          el('span', {}, s.name),
          el('div', { style: { display: 'flex', gap: '6px' } },
            el('button', this._btnStyle('primary'), '▶ Run', { onClick: () => { try { this._j.jskript.run(s.id); } catch (e) { alert('Error: ' + e.message); } } }),
            el('button', this._btnStyle(), 'Edit', { onClick: () => this._showScriptEditor(s) }),
            el('button', this._btnStyle('danger'), '✕', { onClick: () => { this._j.jskript.delete(s.id); this._refreshTab(); } }),
          ),
        ));
      }

      if (!scripts.length) {
        div.appendChild(el('p', { style: { color: 'var(--jsk-fg2)', textAlign: 'center', marginTop: '12px' } }, 'No scripts yet. Click "+ New Script" to write one.'));
      }

      return div;
    }

    _showScriptEditor(existing = null) {
      const overlay = el('div', { style: { position: 'fixed', inset: '0', background: 'rgba(0,0,0,0.8)', zIndex: '2147483648', display: 'flex', alignItems: 'center', justifyContent: 'center' } });
      const modal   = el('div', { style: { background: 'var(--jsk-bg2)', border: '1px solid var(--jsk-border)', borderRadius: '12px', padding: '20px', width: '600px', maxWidth: '90vw', maxHeight: '90vh', display: 'flex', flexDirection: 'column', gap: '12px', fontFamily: 'var(--jsk-font)', color: 'var(--jsk-fg)' } });
      const nameIn  = el('input', { type: 'text', placeholder: 'Script name', value: existing?.name || '', style: { background: 'var(--jsk-bg3)', border: '1px solid var(--jsk-border)', borderRadius: '6px', padding: '8px 12px', color: 'var(--jsk-fg)', fontSize: '14px' } });
      const codeIn  = el('textarea', { placeholder: JSKRIPT_TEMPLATE, style: { background: 'var(--jsk-bg)', border: '1px solid var(--jsk-border)', borderRadius: '6px', padding: '10px', color: 'var(--jsk-fg)', fontSize: '13px', fontFamily: 'var(--jsk-mono)', height: '300px', resize: 'vertical' } });
      if (existing) codeIn.value = existing.code;

      modal.append(
        el('strong', { style: { fontSize: '15px' } }, existing ? 'Edit Script' : 'New JSkript'),
        nameIn,
        codeIn,
        el('div', { style: { display: 'flex', gap: '8px', justifyContent: 'flex-end' } },
          el('button', this._btnStyle(), 'Cancel', { onClick: () => overlay.remove() }),
          el('button', this._btnStyle('primary'), 'Save', {
            onClick: () => {
              const id = existing?.id || uuid();
              this._j.jskript.compile(id, nameIn.value || 'Untitled', codeIn.value);
              overlay.remove();
              this._refreshTab();
            },
          }),
        ),
      );

      overlay.appendChild(modal);
      document.body.appendChild(overlay);
    }

    /* ── Themes tab ── */
    _renderThemes() {
      const div = el('div');
      const current = this._j.themes.getCurrent();

      div.appendChild(el('h4', { style: { margin: '0 0 12px', color: 'var(--jsk-fg2)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.1em' } }, 'Built-in Themes'));

      const grid = el('div', { style: { display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', marginBottom: '20px' } });
      for (const t of this._j.themes.list()) {
        const card = el('div', {
          style: {
            padding: '12px', borderRadius: '8px', cursor: 'pointer', textAlign: 'center',
            border: `2px solid ${t.id === current ? 'var(--jsk-accent)' : 'var(--jsk-border)'}`,
            background: t.vars['--jsk-bg2'] || 'var(--jsk-bg3)',
          },
          onClick: () => { this._j.themes.apply(t.id); this._refreshTab(); },
        },
          el('div', { style: { width: '24px', height: '24px', borderRadius: '50%', background: t.vars['--jsk-accent'], margin: '0 auto 6px' } }),
          el('div', { style: { fontSize: '12px', color: t.vars['--jsk-fg'] || '#fff' } }, t.name),
        );
        grid.appendChild(card);
      }
      div.appendChild(grid);

      div.appendChild(el('h4', { style: { margin: '0 0 12px', color: 'var(--jsk-fg2)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.1em' } }, 'Wallpaper'));

      const wallRow = el('div', { style: { display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' } },
        el('button', this._btnStyle(), 'Image URL', { onClick: () => {
          const url = prompt('Enter image URL:');
          if (url) this._j.themes.setWallpaper(url);
        }}),
        ...['matrix','stars','particles','waves'].map(type =>
          el('button', this._btnStyle(), type.charAt(0).toUpperCase() + type.slice(1), { onClick: () => this._j.themes.setAnimatedWallpaper(type) }),
        ),
        el('button', this._btnStyle('danger'), 'Remove', { onClick: () => this._j.themes.removeWallpaper() }),
      );
      div.appendChild(wallRow);

      div.appendChild(el('h4', { style: { margin: '0 0 12px', color: 'var(--jsk-fg2)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.1em' } }, 'Custom CSS Variables'));
      const customRow = el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } });
      const varInput = el('input', { type: 'text', placeholder: '--jsk-accent: #ff6600', style: { flex: '1', background: 'var(--jsk-bg3)', border: '1px solid var(--jsk-border)', borderRadius: '6px', padding: '8px', color: 'var(--jsk-fg)', fontSize: '13px', fontFamily: 'var(--jsk-mono)' } });
      customRow.appendChild(varInput);
      customRow.appendChild(el('button', this._btnStyle('primary'), 'Apply', { onClick: () => {
        const [k, v] = varInput.value.split(':').map(s => s.trim());
        if (k && v) this._j.themes.applyCustom({ [k]: v });
      }}));
      div.appendChild(customRow);

      return div;
    }

    /* ── Tweaks tab ── */
    _renderTweaks() {
      const div = el('div');
      const cats = this._j.tweaks.categories();

      for (const cat of cats) {
        div.appendChild(el('h4', { style: { margin: '0 0 8px', color: 'var(--jsk-fg2)', fontSize: '12px', textTransform: 'uppercase', letterSpacing: '0.1em' } }, cat));
        for (const def of TWEAKS_DEFS.filter(d => d.cat === cat)) {
          div.appendChild(this._renderTweak(def));
        }
        div.appendChild(el('div', { style: { height: '8px' } }));
      }
      return div;
    }

    _renderTweak(def) {
      const val = this._j.tweaks.get(def.id);
      const row = el('div', { style: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--jsk-border)22' } });
      row.appendChild(el('label', { style: { fontSize: '13px', cursor: 'pointer' } }, def.label));

      let ctrl;
      if (def.type === 'toggle') {
        ctrl = el('button', {
          class: 'jskid-toggle' + (val ? ' on' : ''),
          style: { width: '38px', height: '20px', borderRadius: '10px', border: 'none', cursor: 'pointer', background: val ? 'var(--jsk-accent)' : 'var(--jsk-bg3)', transition: 'background 0.2s', flexShrink: '0', position: 'relative' },
          onClick(e) {
            const newVal = !this._j?.tweaks.get(def.id);
            // use closure from outer scope
          },
        });
        ctrl.addEventListener('click', () => {
          const newVal = !this._j.tweaks.get(def.id);
          this._j.tweaks.set(def.id, newVal);
          ctrl.style.background = newVal ? 'var(--jsk-accent)' : 'var(--jsk-bg3)';
        });
        const knob = el('div', { style: { position: 'absolute', top: '2px', left: val ? '20px' : '2px', width: '16px', height: '16px', borderRadius: '50%', background: '#fff', transition: 'left 0.2s' } });
        ctrl.appendChild(knob);
        ctrl.addEventListener('click', () => {
          knob.style.left = knob.style.left === '2px' ? '20px' : '2px';
        });

      } else if (def.type === 'range') {
        const label = el('span', { style: { width: '40px', textAlign: 'right', color: 'var(--jsk-fg2)', fontSize: '12px' } }, String(val));
        ctrl = el('div', { style: { display: 'flex', gap: '8px', alignItems: 'center' } },
          el('input', {
            type: 'range', min: String(def.min), max: String(def.max), step: String(def.step), value: String(val),
            style: { accentColor: 'var(--jsk-accent)', cursor: 'pointer' },
            onInput(e) { label.textContent = e.target.value; },
            onChange(e) {
              this._j?.tweaks.set(def.id, parseFloat(e.target.value));
            }.bind(this),
          }),
          label,
        );
        ctrl.querySelector('input').addEventListener('change', e => {
          this._j.tweaks.set(def.id, parseFloat(e.target.value));
          label.textContent = e.target.value;
        });

      } else if (def.type === 'color') {
        ctrl = el('input', { type: 'color', value: val, style: { cursor: 'pointer', border: 'none', background: 'none', width: '36px', height: '28px' } });
        ctrl.addEventListener('change', e => this._j.tweaks.set(def.id, e.target.value));

      } else if (def.type === 'textarea') {
        ctrl = el('button', this._btnStyle(), 'Edit CSS', { onClick: () => this._editTextTweak(def) });
      } else {
        ctrl = el('span', {}, String(val));
      }

      row.appendChild(ctrl);
      return row;
    }

    _editTextTweak(def) {
      const overlay = el('div', { style: { position: 'fixed', inset: '0', background: 'rgba(0,0,0,0.8)', zIndex: '2147483648', display: 'flex', alignItems: 'center', justifyContent: 'center' } });
      const ta = el('textarea', { placeholder: '/* Your CSS here */', style: { width: '500px', height: '300px', background: 'var(--jsk-bg)', border: '1px solid var(--jsk-border)', borderRadius: '8px', padding: '12px', color: 'var(--jsk-fg)', fontFamily: 'var(--jsk-mono)', fontSize: '13px' } });
      ta.value = this._j.tweaks.get(def.id) || '';
      const modal = el('div', { style: { background: 'var(--jsk-bg2)', border: '1px solid var(--jsk-border)', borderRadius: '12px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '12px', fontFamily: 'var(--jsk-font)', color: 'var(--jsk-fg)' } },
        el('strong', {}, def.label),
        ta,
        el('div', { style: { display: 'flex', gap: '8px', justifyContent: 'flex-end' } },
          el('button', this._btnStyle(), 'Cancel', { onClick: () => overlay.remove() }),
          el('button', this._btnStyle('primary'), 'Apply', { onClick: () => { this._j.tweaks.set(def.id, ta.value); overlay.remove(); } }),
        ),
      );
      overlay.appendChild(modal);
      document.body.appendChild(overlay);
    }

    /* ── Designs tab ── */
    _renderDesigns() {
      const div = el('div');
      const current = this._j.designs.getCurrent();

      for (const d of this._j.designs.list()) {
        const card = el('div', {
          style: {
            background: 'var(--jsk-bg3)', borderRadius: '10px', padding: '14px 16px', marginBottom: '10px',
            border: `2px solid ${d.id === current ? 'var(--jsk-accent)' : 'var(--jsk-border)'}`,
            cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          },
          onClick: () => { this._j.designs.apply(d.id); this._refreshTab(); },
        },
          el('div', {},
            el('div', { style: { fontSize: '15px', marginBottom: '4px' } }, d.icon + '  ' + d.name),
            el('div', { style: { fontSize: '12px', color: 'var(--jsk-fg2)' } }, d.description),
          ),
          d.id === current ? el('span', { style: { color: 'var(--jsk-accent)', fontSize: '18px' } }, '✓') : '',
        );
        div.appendChild(card);
      }
      return div;
    }

    /* ── Changelog tab ── */
    _renderChangelog() {
      const div = el('div');
      for (const entry of CHANGELOG) {
        div.appendChild(el('div', { style: { marginBottom: '20px' } },
          el('div', { style: { display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' } },
            el('strong', { style: { fontSize: '14px', color: 'var(--jsk-accent)' } }, 'v' + entry.version),
            el('span', { style: { color: 'var(--jsk-fg2)', fontSize: '12px' } }, entry.date),
          ),
          el('ul', { style: { margin: '0', paddingLeft: '18px', color: 'var(--jsk-fg2)', lineHeight: '1.8' } },
            ...entry.notes.map(n => el('li', {}, n)),
          ),
        ));
      }
      return div;
    }

    /* ── Helpers ── */
    _refreshTab() {
      const body = this._panel?.querySelector('[style*="overflow-y: auto"]');
      if (body) { body.innerHTML = ''; body.appendChild(this._renderTab(this._activeTab)); }
    }

    _btnStyle(variant = '') {
      const styles = {
        '':        { background: 'var(--jsk-bg3)', color: 'var(--jsk-fg)',    border: '1px solid var(--jsk-border)' },
        'primary': { background: 'var(--jsk-accent)', color: '#fff',          border: 'none' },
        'danger':  { background: '#c0392b',           color: '#fff',          border: 'none' },
      };
      const s = styles[variant] || styles[''];
      return { style: { ...s, padding: '5px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', whiteSpace: 'nowrap', fontFamily: 'var(--jsk-font)' } };
    }

    _toggleBtn(active, onClick) {
      const btn = el('button', {
        style: {
          width: '40px', height: '22px', borderRadius: '11px', border: 'none', cursor: 'pointer',
          background: active ? 'var(--jsk-accent)' : 'var(--jsk-bg3)', transition: 'background 0.2s',
          position: 'relative', flexShrink: '0',
        },
        onClick,
      });
      const knob = el('div', { style: { position: 'absolute', top: '3px', left: active ? '21px' : '3px', width: '16px', height: '16px', borderRadius: '50%', background: '#fff', transition: 'left 0.2s' } });
      btn.appendChild(knob);
      return btn;
    }
  }

  /* ─── JSKRIPT TEMPLATE ──────────────────────────────────────────────────── */
  const JSKRIPT_TEMPLATE = `// JSkript – available globals:
// onMessage(fn)       – fires when a new AI message arrives
// onGenerate(fn)      – fires when generation starts
// onGenerateDone(fn)  – fires when generation finishes
// sendMessage(text)   – send a message in the current chat
// injectPrompt(id, text) – add text to the system prompt
// removePrompt(id)    – remove an injected system prompt
// useTool(id, args)   – execute a registered tool
// store.get(key) / store.set(key, val)  – persistent storage
// log(...args)        – console.log with [JSkript] prefix
// api                 – raw JSkidAPI instance

// Example: auto-respond with current time
onMessage((msg) => {
  if (msg.content?.includes('time')) {
    sendMessage('The current time is: ' + new Date().toLocaleTimeString());
  }
});
`;

  /* ─── MAIN JSKID OBJECT ─────────────────────────────────────────────────── */
  const jskid = {
    version: VERSION,
    api:     new JSkidAPI(),
    bus,
    store:   Store,
  };

  jskid.addons   = new AddonManager(jskid.api);
  jskid.tools    = new ToolSystem(jskid.api);
  jskid.jskript  = new JSkriptInterpreter(jskid.api, jskid.tools);
  jskid.themes   = new ThemeManager();
  jskid.tweaks   = new TweaksManager();
  jskid.designs  = new DesignManager();
  jskid.ui       = new UIManager(jskid);

  /* ─── BOOT ──────────────────────────────────────────────────────────────── */
  async function boot() {
    console.log(`%c✦ JSkid v${VERSION} booting...`, 'color:#7c6af7;font-weight:bold;font-size:14px');

    jskid.themes.init();
    jskid.designs.init();
    jskid.tweaks.init();
    await jskid.addons.loadSaved();
    jskid.ui.init();

    // Expose globally for addons and devs
    global.JSkid = jskid;
    global.__JSKID__ = true;

    // Announce force-reload helper
    global.JSkidForceUpdate = () => {
      GM.setValue('jskid_force_reload', true);
      location.reload();
    };

    console.log('%c✦ JSkid ready! Access via window.JSkid', 'color:#7c6af7;font-weight:bold');
    bus.emit('jskid:ready', jskid);
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    setTimeout(boot, 100);
  } else {
    document.addEventListener('DOMContentLoaded', () => setTimeout(boot, 100));
  }

})(typeof unsafeWindow !== 'undefined' ? unsafeWindow : window);
