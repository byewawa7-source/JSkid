/**
 * JSkid Core Engine v3.0.0
 * The ultimate modular JanitorAI modification framework.
 */

(function() {
    if (window.JSkid) return;

    // ==========================================
    // 1. CORE NAMESPACE & STATE
    // ==========================================
    window.JSkid = {
        version: "3.0.0",
        API: {
            currentChar: null,   // Hidden character data for rippers
            lastPayload: null,   // Last LLM request payload
            currentChatId: null
        },
        Config: {
            theme: 'default',
            design: 'default',
            tweaks: {
                compactChat: false,
                hideAvatars: false,
                blurImages: false
            },
            customTheme: {
                bg: '#11111b', fg: '#cdd6f4', accent: '#cba6f7', wallpaper: ''
            },
            jskriptCode: ''
        },
        Addons: { list: {}, pending: [] },
        Themes: { list: {} },
        Designs: { list: {} },
        JSkript: {
            events: {},
            effects: {},
            conditions: {},
            compiledTree: []
        }
    };

    const J = window.JSkid;

    // ==========================================
    // 2. STORAGE MANAGEMENT
    // ==========================================
    const Storage = {
        save: () => localStorage.setItem('jskid_config', JSON.stringify(J.Config)),
        load: () => {
            try {
                const saved = localStorage.getItem('jskid_config');
                if (saved) J.Config = { ...J.Config, ...JSON.parse(saved) };
            } catch(e) { console.error('[JSkid] Storage Error:', e); }
        }
    };

    // ==========================================
    // 3. JSKRIPT ENGINE (Skript Syntax)
    // ==========================================
    const JSkriptEngine = {
        // Registers building blocks for the language
        registerEvent: (name, triggerFn) => J.JSkript.events[name] = triggerFn,
        registerEffect: (regex, handlerFn) => J.JSkript.effects[regex] = handlerFn,
        registerCondition: (regex, handlerFn) => J.JSkript.conditions[regex] = handlerFn,

        compile: function(code) {
            J.Config.jskriptCode = code;
            Storage.save();
            const lines = code.split('\n').map(l => l.trimEnd()).filter(l => l.trim() && !l.trim().startsWith('#'));
            
            // Indentation-based AST Parser
            let root = [];
            let stack = [{ indent: -1, children: root }];

            for (let line of lines) {
                const indent = line.search(/\S|$/);
                const text = line.trim();
                const node = { text, children: [] };

                while (stack.length > 0 && stack[stack.length - 1].indent >= indent) {
                    stack.pop();
                }
                stack[stack.length - 1].children.push(node);
                stack.push({ indent, children: node.children });
            }

            J.JSkript.compiledTree = root;
            console.log(`[JSkript] Compiled ${root.length} root events.`);
        },

        executeEvent: function(eventName, context) {
            for (let node of J.JSkript.compiledTree) {
                let eventMatch = node.text.match(/^on (.*):$/i);
                if (eventMatch && eventMatch[1].toLowerCase() === eventName.toLowerCase()) {
                    this.executeBlock(node.children, context);
                }
            }
        },

        executeBlock: function(nodes, context) {
            for (let node of nodes) {
                let text = node.text;

                // Handle IF conditions
                if (text.toLowerCase().startsWith('if ')) {
                    let conditionText = text.substring(3).replace(/:$/, '').trim();
                    if (this.evaluateCondition(conditionText, context)) {
                        this.executeBlock(node.children, context);
                    }
                    continue;
                }

                // Handle Effects
                let effectFound = false;
                for (let regexStr in J.JSkript.effects) {
                    let regex = new RegExp(`^${regexStr}$`, 'i');
                    let match = text.match(regex);
                    if (match) {
                        J.JSkript.effects[regexStr](context, match.slice(1));
                        effectFound = true;
                        break;
                    }
                }
                if (!effectFound) console.warn(`[JSkript] Unknown effect: ${text}`);
            }
        },

        evaluateCondition: function(text, context) {
            for (let regexStr in J.JSkript.conditions) {
                let regex = new RegExp(`^${regexStr}$`, 'i');
                let match = text.match(regex);
                if (match) {
                    return J.JSkript.conditions[regexStr](context, match.slice(1));
                }
            }
            console.warn(`[JSkript] Unknown condition: ${text}`);
            return false;
        }
    };

    // --- Core JSkript API Registry ---
    JSkriptEngine.registerEffect('inject memory "(.*)"', (ctx, args) => {
        if (ctx.payload && ctx.payload.userConfig) {
            ctx.payload.userConfig.llm_prompt += `\n[System Note: ${args[0]}]`;
        }
    });
    
    JSkriptEngine.registerEffect('cancel event', (ctx) => {
        ctx.cancelled = true;
    });

    JSkriptEngine.registerCondition('message contains "(.*)"', (ctx, args) => {
        return ctx.message && ctx.message.toLowerCase().includes(args[0].toLowerCase());
    });

    // ==========================================
    // 4. THEMES & DESIGNS ENGINE
    // ==========================================
    J.Themes.register = (id, name, cssVars, customCss = "") => {
        J.Themes.list[id] = { name, cssVars, customCss };
    };

    // Default Themes
    J.Themes.register('default', 'JSkid Default (Catppuccin)', {
        '--jskid-bg': '#1e1e2e', '--jskid-fg': '#cdd6f4', '--jskid-accent': '#cba6f7'
    });
    J.Themes.register('hacker', 'Matrix Hacker', {
        '--jskid-bg': '#050505', '--jskid-fg': '#00ff00', '--jskid-accent': '#00cc00'
    });

    J.Designs.register = (id, name, applyFn, removeFn) => {
        J.Designs.list[id] = { name, apply: applyFn, remove: removeFn };
    };

    // Default Design (Vanilla)
    J.Designs.register('default', 'Vanilla JanitorAI', () => {}, () => {});

    // Floating Dock Design (Moves navigation to a bottom floating dock)
    J.Designs.register('floating_dock', 'macOS Floating Dock', () => {
        const style = document.createElement('style');
        style.id = 'jskid-design-floating';
        style.innerHTML = `
            header nav {
                position: fixed !important; bottom: 20px !important; left: 50% !important;
                transform: translateX(-50%) !important; border-radius: 30px !important;
                background: rgba(0,0,0,0.8) !important; backdrop-filter: blur(10px) !important;
                padding: 10px 20px !important; z-index: 99999 !important; border: 1px solid rgba(255,255,255,0.2) !important;
                width: auto !important; top: auto !important; flex-direction: row !important;
            }
            main { padding-bottom: 100px !important; }
        `;
        document.head.appendChild(style);
    }, () => {
        const style = document.getElementById('jskid-design-floating');
        if (style) style.remove();
    });


    const UIEngine = {
        applySettings: function() {
            // Apply Tweaks
            const rootClasses = document.documentElement.classList;
            J.Config.tweaks.compactChat ? rootClasses.add('jskid-tweak-compact') : rootClasses.remove('jskid-tweak-compact');
            J.Config.tweaks.hideAvatars ? rootClasses.add('jskid-tweak-no-avatars') : rootClasses.remove('jskid-tweak-no-avatars');
            J.Config.tweaks.blurImages ? rootClasses.add('jskid-tweak-blur-images') : rootClasses.remove('jskid-tweak-blur-images');

            // Apply Theme
            let theme = J.Themes.list[J.Config.theme];
            if (!theme) theme = J.Themes.list['default'];
            
            const root = document.documentElement;
            for (let [key, val] of Object.entries(theme.cssVars)) {
                root.style.setProperty(key, val);
            }
            if (J.Config.customTheme.wallpaper) {
                document.body.style.backgroundImage = `url('${J.Config.customTheme.wallpaper}')`;
                document.body.style.backgroundSize = 'cover';
                document.body.style.backgroundAttachment = 'fixed';
            } else {
                document.body.style.backgroundImage = 'none';
            }

            // Custom Theme CSS
            let themeStyle = document.getElementById('jskid-theme-customcss');
            if (!themeStyle) {
                themeStyle = document.createElement('style');
                themeStyle.id = 'jskid-theme-customcss';
                document.head.appendChild(themeStyle);
            }
            themeStyle.innerHTML = theme.customCss || "";

            // Apply Design
            if (this.currentDesign && J.Designs.list[this.currentDesign]) {
                J.Designs.list[this.currentDesign].remove();
            }
            this.currentDesign = J.Config.design;
            if (J.Designs.list[this.currentDesign]) {
                J.Designs.list[this.currentDesign].apply();
            }
        }
    };

    // ==========================================
    // 5. NETWORK PROXY (Intercepts JSON APIs)
    // ==========================================
    const ProxyEngine = {
        init: function() {
            const origFetch = window.fetch;
            window.fetch = async function(...args) {
                let resource = args[0];
                let config = args[1] || {};
                let url = typeof resource === 'string' ? resource : (resource instanceof Request ? resource.url : '');

                // JSkript Hook: Intercepting outgoing messages to the LLM
                if (url.includes('/generateAlpha') && config.method === 'POST' && config.body) {
                    try {
                        let payload = JSON.parse(config.body);
                        if (payload.chatMessages && payload.chatMessages.length > 0) {
                            let lastMsg = payload.chatMessages[payload.chatMessages.length - 1];
                            if (!lastMsg.is_bot) {
                                // Create execution context for JSkript
                                let context = {
                                    message: lastMsg.message,
                                    payload: payload,
                                    cancelled: false
                                };
                                
                                JSkriptEngine.executeEvent('message send', context);
                                
                                if (context.cancelled) {
                                    console.log('[JSkid] LLM request cancelled by JSkript.');
                                    return new Response(JSON.stringify({error: "Cancelled by JSkid"}), {status: 200});
                                }
                                
                                config.body = JSON.stringify(context.payload);
                                args[1] = config;
                                J.API.lastPayload = context.payload;
                            }
                        }
                    } catch(e) { console.error('[JSkid Proxy] Error parsing outgoing payload:', e); }
                }

                const response = await origFetch.apply(this, args);

                // Hidden Character Information Ripper
                if (url.includes('/hampter/characters/')) {
                    response.clone().json().then(data => {
                        J.API.currentChar = data;
                        JSkriptEngine.executeEvent('character load', { character: data });
                        console.log('[JSkid Proxy] Background character data extracted.');
                    }).catch(() => {});
                }

                return response;
            };
        }
    };

    // ==========================================
    // 6. ADDON SYSTEM
    // ==========================================
    J.Addons.register = function(addonObj) {
        if (!addonObj.name || !addonObj.version || typeof addonObj.init !== 'function') return;
        J.Addons.pending.push(addonObj);
        this.resolve();
    };
    J.Addons.resolve = function() {
        let resolved = true;
        while (resolved && J.Addons.pending.length > 0) {
            resolved = false;
            for (let i = J.Addons.pending.length - 1; i >= 0; i--) {
                let addon = J.Addons.pending[i];
                let depsMet = addon.dependencies ? addon.dependencies.every(d => J.Addons.list[d]) : true;
                if (depsMet) {
                    try {
                        addon.init(J);
                        J.Addons.list[addon.name] = addon;
                        J.Addons.pending.splice(i, 1);
                        resolved = true;
                        console.log(`[JSkid Addons] Loaded: ${addon.name} v${addon.version}`);
                    } catch (e) {
                        console.error(`[JSkid Addons] Init error in ${addon.name}:`, e);
                        J.Addons.pending.splice(i, 1);
                    }
                }
            }
        }
    };

    // ==========================================
    // 7. JSKID GRAPHICAL UI
    // ==========================================
    const GUI = {
        init: function() {
            this.injectBaseCSS();
            this.buildElements();
            this.bindEvents();
            this.renderDropdowns();
        },
        
        injectBaseCSS: function() {
            const style = document.createElement('style');
            style.innerHTML = `
                /* JSkid Internal UI */
                #jskid-bubble {
                    position: fixed; bottom: 20px; right: 20px; width: 60px; height: 60px;
                    background: linear-gradient(135deg, var(--jskid-accent), #f5c2e7);
                    border-radius: 50%; cursor: pointer; z-index: 999999;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center;
                    font-weight: 900; color: #11111b; font-family: sans-serif; font-size: 20px; border: 2px solid rgba(255,255,255,0.2);
                    transition: transform 0.2s cubic-bezier(0.175, 0.885, 0.32, 1.275);
                }
                #jskid-bubble:hover { transform: scale(1.15) rotate(-5deg); }

                #jskid-modal {
                    position: fixed; bottom: 90px; right: 20px; width: 450px; height: 600px;
                    background: rgba(30, 30, 46, 0.98); backdrop-filter: blur(15px);
                    color: var(--jskid-fg); border: 1px solid var(--jskid-accent);
                    border-radius: 12px; z-index: 999999; display: none; flex-direction: column;
                    box-shadow: 0 15px 40px rgba(0,0,0,0.8); font-family: monospace;
                }
                #jskid-modal.open { display: flex; animation: jskidPopUp 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275); }
                @keyframes jskidPopUp { from { transform: translateY(20px) scale(0.95); opacity: 0; } to { transform: translateY(0) scale(1); opacity: 1; } }

                .js-header { background: rgba(0,0,0,0.4); padding: 15px; text-align: center; font-weight: bold; border-bottom: 1px solid var(--jskid-accent); font-size: 16px; letter-spacing: 1px; }
                .js-nav { display: flex; background: rgba(0,0,0,0.2); }
                .js-nav button { flex: 1; padding: 12px 0; background: none; border: none; color: inherit; border-bottom: 2px solid transparent; cursor: pointer; transition: 0.2s; font-family: monospace; font-size: 13px; }
                .js-nav button:hover { background: rgba(255,255,255,0.05); }
                .js-nav button.active { border-color: var(--jskid-accent); color: var(--jskid-accent); font-weight: bold; background: rgba(203, 166, 247, 0.1); }
                
                .js-content { flex: 1; padding: 20px; overflow-y: auto; }
                .js-tab { display: none; }
                .js-tab.active { display: block; animation: jskidFade 0.2s; }
                @keyframes jskidFade { from { opacity: 0; } to { opacity: 1; } }

                .js-input, .js-select { width: 100%; background: #11111b; color: var(--jskid-fg); border: 1px solid #45475a; padding: 10px; border-radius: 6px; margin: 5px 0 15px; font-family: monospace; box-sizing: border-box; }
                .js-btn { background: var(--jskid-accent); color: #11111b; border: none; padding: 10px; border-radius: 6px; cursor: pointer; font-weight: bold; width: 100%; transition: 0.2s; font-family: monospace; font-size: 14px; }
                .js-btn:hover { opacity: 0.8; transform: translateY(-1px); }
                .js-btn-green { background: #a6e3a1; color: #11111b; }
                
                .js-tweak-lbl { display: flex; align-items: center; padding: 10px 0; border-bottom: 1px solid #313244; cursor: pointer; }
                .js-tweak-lbl input { margin-right: 10px; width: 16px; height: 16px; accent-color: var(--jskid-accent); }

                /* Tweak CSS implementations */
                .jskid-tweak-compact .prose { font-size: 14px !important; line-height: 1.4 !important; }
                .jskid-tweak-compact [data-testid="message-container"] { padding-top: 5px !important; padding-bottom: 5px !important; }
                .jskid-tweak-no-avatars img.avatar { display: none !important; }
                .jskid-tweak-blur-images img:not(.avatar) { filter: blur(20px); transition: filter 0.3s ease; }
                .jskid-tweak-blur-images img:not(.avatar):hover { filter: blur(0px); }
            `;
            document.head.appendChild(style);
        },

        buildElements: function() {
            // Bubble
            const bubble = document.createElement('div');
            bubble.id = 'jskid-bubble';
            bubble.innerText = 'JS';
            bubble.onclick = () => {
                const m = document.getElementById('jskid-modal');
                m.classList.toggle('open');
            };
            document.body.appendChild(bubble);

            // Modal
            const modal = document.createElement('div');
            modal.id = 'jskid-modal';
            modal.innerHTML = `
                <div class="js-header">JSkid v${J.version}</div>
                <div class="js-nav">
                    <button class="active" data-tab="home">Status</button>
                    <button data-tab="themes">UI / Themes</button>
                    <button data-tab="jskript">JSkript</button>
                    <button data-tab="addons">Addons</button>
                </div>
                <div class="js-content">
                    
                    <!-- HOME -->
                    <div id="js-tab-home" class="js-tab active">
                        <h2>System Status</h2>
                        <p style="color:#a6e3a1;">● Core Engine Active</p>
                        <p style="color:#a6e3a1;">● Network Proxy Active</p>
                        <hr style="border-color:#45475a; margin: 15px 0;">
                        <h3>Changelog</h3>
                        <ul style="font-size:12px; color:#bac2de; padding-left:15px; line-height:1.5;">
                            ${J.changelog.map(l => `<li>${l}</li>`).join('')}
                        </ul>
                    </div>

                    <!-- THEMES & DESIGNS -->
                    <div id="js-tab-themes" class="js-tab">
                        <h3>Design Layout</h3>
                        <p style="font-size:11px; color:#a6adc8; margin-top:-10px;">Select a structural layout modification.</p>
                        <select id="js-select-design" class="js-select"></select>

                        <h3>Color Theme</h3>
                        <select id="js-select-theme" class="js-select"></select>

                        <h3>Custom Wallpaper URL</h3>
                        <input type="text" id="js-val-wallpaper" class="js-input" placeholder="https://... (.gif, .mp4, .png)">
                        
                        <h3>Tweaks</h3>
                        <label class="js-tweak-lbl"><input type="checkbox" id="js-twk-compact"> Compact Chat Bubbles</label>
                        <label class="js-tweak-lbl"><input type="checkbox" id="js-twk-avatars"> Hide All Avatars</label>
                        <label class="js-tweak-lbl"><input type="checkbox" id="js-twk-blur"> Blur NSFW Images (Hover reveal)</label>

                        <button id="js-btn-save-ui" class="js-btn" style="margin-top:20px;">Save & Apply Settings</button>
                    </div>

                    <!-- JSKRIPT -->
                    <div id="js-tab-jskript" class="js-tab">
                        <h3>JSkript Editor</h3>
                        <p style="font-size:11px; color:#a6adc8; margin-top:-10px;">Write custom rules. Use Skript syntax.</p>
                        <textarea id="js-val-code" class="js-input" style="height:300px; resize:none;" spellcheck="false"></textarea>
                        <button id="js-btn-compile" class="js-btn js-btn-green">Compile & Run Script</button>
                    </div>

                    <!-- ADDONS -->
                    <div id="js-tab-addons" class="js-tab">
                        <h3>Loaded Modules</h3>
                        <div id="js-addon-container" style="background:#11111b; padding:15px; border-radius:6px; border:1px solid #45475a; font-size:12px;"></div>
                    </div>

                </div>
            `;
            document.body.appendChild(modal);
        },

        renderDropdowns: function() {
            const desSelect = document.getElementById('js-select-design');
            desSelect.innerHTML = '';
            for (let id in J.Designs.list) {
                desSelect.innerHTML += `<option value="${id}">${J.Designs.list[id].name}</option>`;
            }
            desSelect.value = J.Config.design;

            const themeSelect = document.getElementById('js-select-theme');
            themeSelect.innerHTML = '';
            for (let id in J.Themes.list) {
                themeSelect.innerHTML += `<option value="${id}">${J.Themes.list[id].name}</option>`;
            }
            themeSelect.value = J.Config.theme;
        },

        bindEvents: function() {
            // Tab Switching
            document.querySelectorAll('.js-nav button').forEach(btn => {
                btn.onclick = (e) => {
                    document.querySelectorAll('.js-nav button').forEach(b => b.classList.remove('active'));
                    document.querySelectorAll('.js-tab').forEach(t => t.classList.remove('active'));
                    e.target.classList.add('active');
                    const tab = e.target.getAttribute('data-tab');
                    document.getElementById(`js-tab-${tab}`).classList.add('active');

                    if (tab === 'addons') {
                        const cnt = document.getElementById('js-addon-container');
                        const keys = Object.keys(J.Addons.list);
                        cnt.innerHTML = keys.length > 0 
                            ? keys.map(k => `<div style="margin-bottom:8px;"><span style="color:var(--jskid-accent)">✦</span> <b>${k}</b> <span style="color:#6c7086">v${J.Addons.list[k].version}</span></div>`).join('') 
                            : "<i>No Addons registered.</i>";
                    }
                };
            });

            // UI Save Button
            document.getElementById('js-btn-save-ui').onclick = () => {
                J.Config.design = document.getElementById('js-select-design').value;
                J.Config.theme = document.getElementById('js-select-theme').value;
                J.Config.customTheme.wallpaper = document.getElementById('js-val-wallpaper').value;
                
                J.Config.tweaks.compactChat = document.getElementById('js-twk-compact').checked;
                J.Config.tweaks.hideAvatars = document.getElementById('js-twk-avatars').checked;
                J.Config.tweaks.blurImages = document.getElementById('js-twk-blur').checked;

                Storage.save();
                UIEngine.applySettings();
            };

            // JSkript Compile
            document.getElementById('js-btn-compile').onclick = () => {
                const code = document.getElementById('js-val-code').value;
                JSkriptEngine.compile(code);
                alert(`JSkript Compiled! Loaded ${J.JSkript.compiledTree.length} Event Handlers.`);
            };
        },

        syncInputsToConfig: function() {
            document.getElementById('js-twk-compact').checked = J.Config.tweaks.compactChat;
            document.getElementById('js-twk-avatars').checked = J.Config.tweaks.hideAvatars;
            document.getElementById('js-twk-blur').checked = J.Config.tweaks.blurImages;
            document.getElementById('js-val-wallpaper').value = J.Config.customTheme.wallpaper || '';
            document.getElementById('js-val-code').value = J.Config.jskriptCode || 
`# Welcome to JSkript
# Event: message send
on message send:
    if message contains "smile":
        inject memory "The user smiled. Acknowledge it gently."`;
        }
    };

    // ==========================================
    // 8. BOOTSTRAP INIT
    // ==========================================
    function boot() {
        Storage.load();
        ProxyEngine.init();
        
        // Wait for DOM to build UI
        const buildUI = () => {
            GUI.init();
            GUI.syncInputsToConfig();
            UIEngine.applySettings();
            
            // Auto-compile saved JSkript
            if (J.Config.jskriptCode) {
                JSkriptEngine.compile(J.Config.jskriptCode);
            }
            console.log(`%c[JSkid] Core Engine v${J.version} Fully Operational.`, 'color: #a6e3a1; font-weight: bold; font-size: 16px;');
        };

        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', buildUI);
        } else {
            buildUI();
        }
    }

    boot();

})();
