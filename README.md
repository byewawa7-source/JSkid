# ✦ JSkid

**The JanitorAI power-user framework.**  
A Tampermonkey userscript that turns JanitorAI into your own fully-customisable platform.

---

## Installation

1. Install [Tampermonkey](https://www.tampermonkey.net/) in your browser.
2. Create a new script and paste the contents of `jskid-loader.user.js`.
3. **Edit the `JSKID_CORE_URL` constant** at the top of the loader to point at your GitHub raw URL  
   (e.g. `https://raw.githubusercontent.com/YOUR_USERNAME/jskid/main/jskid-core.js`).
4. Host `jskid-core.js` at that URL (fork this repo and push it there).
5. Visit JanitorAI — the **✦ bubble** appears in the bottom-right corner.

> **Quick local test:** Replace `JSKID_CORE_URL` with a `data:` URI or paste `jskid-core.js` directly inside the loader function.

---

## Features

### 🧩 Addon System
- Register, install, enable/disable, and uninstall addons at runtime.
- Dependency resolution: addons declare `dependencies: ['other-addon-id']`.
- Addons receive the full JSkid API, a config object, and the event bus.
- See `addon-example-message-logger.js` for a complete working example.

### ✏️ JSkript
- Write JavaScript-based behaviour scripts inside the JSkid menu.
- Sandboxed context with helpers: `onMessage`, `sendMessage`, `injectPrompt`, `useTool`, `store`, etc.
- Scripts are saved to persistent storage and can be run on demand or triggered by events.

### 🛠️ Tool System
- Addons and JSkripts register **tools** (`id`, `name`, `description`, `execute`).
- Tools can be injected into specific chats via the Tools tab.
- Tools receive `(args, context, api)` and can call any JSkid API method.

### 🎨 Theme Engine
- 6 built-in themes: **Dark**, **Ocean**, **Neon Synthwave**, **Rose Garden**, **Forest**, **Light**.
- Full CSS variable overriding for fine-grained control.
- Wallpaper support: image URL or one of 4 animated canvases — **Matrix**, **Stars**, **Particles**, **Waves**.

### ⚙️ Tweaks (40+)
Organised into categories: Layout, Typography, Bubbles, Behaviour, Notifications, Appearance, Privacy, Power.

Highlights:
- Chat max-width, font size, line height
- Compact messages, floating input bar
- Bubble colours, border radius, drop shadows
- Show timestamps, word count on hover
- Auto-scroll, Send-on-Enter, double-click to edit
- Auto-save drafts, auto-retry on error
- Sound/desktop notifications
- Hide ads, blur NSFW images, hide header
- Block analytics, reduce motion
- Custom CSS injection

### 🖼️ Design System
Completely re-skin the JanitorAI UI:

| Design | Description |
|--------|-------------|
| **Default** | Standard JanitorAI with JSkid enhancements |
| **Minimal** | Distraction-free, centered reading layout |
| **Terminal** | Green-on-black monospace terminal aesthetic |
| **Floating Windows** | Collapsible sidebar + floating chat panel |
| **Cozy** | Warm, rounded, generous spacing |
| **Dock + Desktop** | macOS-style dock at the bottom |

### 🔄 Auto-update via GitHub
The loader caches `jskid-core.js` for 1 hour then re-fetches automatically.  
Force an immediate update from the browser console:
```js
JSkidForceUpdate(); // clears cache and reloads
```

---

## Developer API

After boot, `window.JSkid` is available everywhere:

```js
// Characters
const char = await JSkid.api.getCharacter('char-id-here');

// Chats
const chatId = JSkid.api.getCurrentChatId();
await JSkid.api.sendMessage(chatId, 'Hello!');

// System prompt injection
JSkid.api.injectSystemPrompt('my-injection', 'Always respond in haiku form.');

// SSE generation stream
await JSkid.api.generate(chatId, chunk => console.log(chunk), () => console.log('done'));

// Events
JSkid.bus.on('jskid:ready', (jskid) => console.log('JSkid loaded', jskid.version));
JSkid.bus.on('theme:applied', (id) => console.log('Theme changed to', id));

// Tweaks
JSkid.tweaks.set('font_size', 18);
JSkid.tweaks.set('auto_scroll', true);

// Themes
JSkid.themes.apply('neon');
JSkid.themes.setAnimatedWallpaper('matrix');

// Designs
JSkid.designs.apply('terminal');
```

---

## Writing an Addon

```js
JSkid.addons.register({
  id:           'my-addon',
  name:         'My Addon',
  version:      '1.0.0',
  description:  'Does something cool',
  dependencies: [],           // optional: ['other-addon-id']
  defaultConfig: { foo: 'bar' },

  install(api, config, bus) {
    // your code here — runs when installed/enabled
  },

  uninstall() { /* cleanup */ },
  disable()   { /* pause */   },
});

// Then install it:
await JSkid.addons.install('my-addon', { foo: 'custom' });
```

---

## Writing a JSkript

Open the JSkid menu → **✏️ JSkript** tab → **+ New Script**.

```js
// Greet the user every time AI finishes generating
onGenerateDone(() => {
  log('Generation complete!');
});

// Inject a mood hint into the system prompt
injectPrompt('mood', 'The user is feeling adventurous today.');

// Remove it later
removePrompt('mood');
```

---

## File Structure

```
jskid-loader.user.js           ← Install this in Tampermonkey
jskid-core.js                  ← Host this on GitHub
addon-example-message-logger.js ← Example addon
README.md                      ← This file
```

---

## Changelog

See the **📋 Changes** tab inside the JSkid menu.
