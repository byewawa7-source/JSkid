import os
import re
import json
import httpx
import time
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional
from pathlib import Path

# ==========================================
# 1. CONFIGURATION & STATE MANAGEMENT
# ==========================================
CONFIG_FILE = "jskid_config.json"

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

# Global config state (in production, use a proper store/DB)
GLOBAL_CONFIG = load_config()

# ==========================================
# 2. AESTHETIC UI ENGINE (Based on terminal-ui-design skill)
# ==========================================
class AestheticEngine:
    def __init__(self, theme: str = "cyberpunk"):
        self.theme = theme
        self.themes = {
            "cyberpunk": {
                "colors": {"border": "\033[95m", "text": "\033[96m", "accent": "\033[93m", "reset": "\033[0m"},
                "chars": {"tl": "╔", "tr": "╗", "bl": "╚", "br": "╝", "h": "═", "v": "║", "t_left": "╠", "t_right": "╣"},
                "header_style": "bold"
            },
            "minimalist": {
                "colors": {"border": "\033[90m", "text": "\033[37m", "accent": "\033[90m", "reset": "\033[0m"},
                "chars": {"tl": "", "tr": "", "bl": "", "br": "", "h": " ", "v": "│", "t_left": "", "t_right": ""},
                "header_style": "plain"
            },
            "retro_crt": {
                "colors": {"border": "\033[32m", "text": "\033[32m", "accent": "\033[32m", "reset": "\033[0m"},
                "chars": {"tl": "+", "tr": "+", "bl": "+", "br": "+", "h": "-", "v": "|", "t_left": "+", "t_right": "+"},
                "header_style": "upper"
            },
            "brutalist": {
                "colors": {"border": "\033[41m\033[97m", "text": "\033[40m\033[97m", "accent": "\033[43m\033[30m", "reset": "\033[0m"},
                "chars": {"tl": "▛", "tr": "▜", "bl": "▙", "br": "▟", "h": "▀", "v": "▌", "t_left": "▌", "t_right": "▐"},
                "header_style": "block"
            }
        }
        self.style = self.themes.get(theme, self.themes["cyberpunk"])

    def _c(self, code: str) -> str:
        return self.style["colors"].get(code, "")

    def _reset(self) -> str:
        return self.style["colors"]["reset"]

    def _pad(self, text: str, width: int, align: str = "left") -> str:
        # Strip ANSI codes for length calculation
        clean_text = re.sub(r'\033\[[0-9;]*m', '', text)
        diff = width - len(clean_text)
        if diff < 0:
            clean_text = clean_text[:width-3] + "..."
            diff = 3
        
        if align == "center":
            left = diff // 2
            right = diff - left
            return " " * left + text + " " * right
        elif align == "right":
            return " " * diff + text
        return text + " " * diff

    def render_box(self, title: str, content_lines: list, width: int = 50) -> str:
        c = self.style["chars"]
        col = self.style["colors"]
        
        # Header
        title_str = f" {title} "
        if self.style["header_style"] == "upper":
            title_str = title_str.upper()
        elif self.style["header_style"] == "bold":
            title_str = f"\033[1m{title_str}\033[0m"
            
        header_inner = self._pad(title_str, width - 4, "center")
        header_line = f"{col['border']}{c['tl']}{c['h'] * 2}{header_inner}{c['h'] * 2}{c['tr']}{self._reset()}"
        
        # Body
        body_lines = []
        for line in content_lines:
            padded = self._pad(line, width - 4, "left")
            body_lines.append(f"{col['border']}{c['v']}{self._reset()} {padded} {col['border']}{c['v']}{self._reset()}")
            
        # Footer
        footer_line = f"{col['border']}{c['bl']}{c['h'] * (width - 2)}{c['br']}{self._reset()}"
        
        return "\n".join([header_line] + body_lines + [footer_line])

    def render_setup_wizard_step(self, step: int, total: int, message: str, input_hint: str = "") -> str:
        lines = [
            f"SETUP WIZARD [{step}/{total}]",
            "-" * 20,
            message,
            ""
        ]
        if input_hint:
            lines.append(f"> {input_hint}")
        return self.render_box("CONFIGURATION", lines)

    def render_status(self, status: str, memory_count: int, theme_name: str) -> str:
        lines = [
            f"System Status : {status}",
            f"Active Memory : {memory_count} items",
            f"UI Theme      : {theme_name.upper()}",
            f"Proxy         : Connected"
        ]
        return self.render_box("JSKID DASHBOARD", lines)

# ==========================================
# 3. CORE LOGIC & PARSING
# ==========================================
class JSkidCore:
    def __init__(self):
        self.memory = []
        self.chars = {}
        self.tools = []
        # Default theme, can be overridden by user command or config
        self.ui_theme = "cyberpunk" 

    def parse_state(self, messages):
        self.memory.clear()
        self.chars.clear()
        self.tools.clear()

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): continue
            
            # Parse Tags
            tags = re.findall(r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|EXT|TOOL|SET_THEME):\s*(.*?)]\s*-->', content, re.DOTALL)
            for tag_type, val in tags:
                val = val.strip()
                if tag_type == "MEM_ADD" and val not in self.memory:
                    self.memory.append(val)
                elif tag_type == "MEM_DEL" and val in self.memory:
                    self.memory.remove(val)
                elif tag_type == "SET_VAR":
                    m = re.match(r'([^=]+)=\s*(.*)', val)
                    if m:
                        k, v = m.groups()
                        self.chars[k.strip()] = v.strip().strip('"\'')
                elif tag_type == "TOOL":
                    try:
                        self.tools.append(json.loads(val))
                    except: pass
                elif tag_type == "SET_THEME":
                    if val.lower() in ["cyberpunk", "minimalist", "retro_crt", "brutalist"]:
                        self.ui_theme = val.lower()

    def sanitize(self, messages):
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                clean.append(msg)
                continue
            
            # Remove internal tags and previous UI renders
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            # Regex to remove the specific ASCII blocks generated by our engine
            content = re.sub(r'(\033\[[0-9;]*m)?[╔╚╔╚╓╒╭+▛].*?(\033\[[0-9;]*m)?[╗╝┘╖╕╮+▜](\033\[[0-9;]*m)?', '', content, flags=re.DOTALL)
            
            content = content.strip()
            
            # Skip user commands that start with / to avoid sending them to LLM as conversation
            if msg["role"] == "user" and content.startswith(('/', '!')):
                continue
                
            if content:
                msg["content"] = content
                clean.append(msg)
        return clean

    def inject_world_state(self, messages):
        if not self.memory and not self.chars:
            return messages
        
        ws = ["\n<world_state>"]
        if self.memory:
            ws.append(f"<mem>{';'.join(self.memory)}</mem>")
        if self.chars:
            ws.append(f"<vars>{';'.join(f'{k}={v}' for k, v in self.chars.items())}</vars>")
        ws.append("</world_state>")
        
        ws_text = "".join(ws)
        injected = False
        for msg in messages:
            if msg["role"] == "system":
                msg["content"] += ws_text
                injected = True
                break
        if not injected:
            messages.insert(0, {"role": "system", "content": ws_text.strip()})
        return messages

# ==========================================
# 4. FASTAPI APPLICATION
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("--- JSkid Proxy Started ---")
    yield

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Helper: Run Setup Wizard Logic ---
async def run_setup_wizard(messages: list, current_config: dict) -> StreamingResponse:
    """
    Intercepts the chat flow to guide the user through setting up API keys.
    This is a simple state machine based on the last user message.
    """
    core = JSkidCore()
    ui = AestheticEngine(theme="cyberpunk") # Wizard always uses high-vis theme
    
    last_msg = messages[-1].get("content", "").strip() if messages else ""
    
    # Determine Step
    step = 1
    if "UPSTREAM_URL" in current_config:
        step = 2
    if "PROXY_KEY" in current_config:
        step = 3 # Done

    if step == 3:
        # Should not happen if called, but safety check
        return JSONResponse(content={"error": "Already configured"})

    response_text = ""
    
    if step == 1:
        if last_msg and last_msg.startswith("http"):
            # Save URL
            current_config["UPSTREAM_URL"] = last_msg
            save_config(current_config)
            response_text = ui.render_setup_wizard_step(2, 2, "URL Saved. Now, please enter your API KEY (or leave blank if none).", "Enter API Key...")
        else:
            response_text = ui.render_setup_wizard_step(1, 2, "Welcome to JSkid Proxy.\nPlease enter the Upstream API URL (e.g., https://api.openai.com/v1/chat/completions)", "Enter URL...")
            
    elif step == 2:
        # Save Key
        key = last_msg if last_msg else None
        current_config["PROXY_KEY"] = key
        save_config(current_config)
        response_text = ui.render_setup_wizard_step(2, 2, "Configuration Complete!\nYour proxy is now ready.", "Type anything to start chatting.")

    # We simulate a streaming response for the wizard so JanitorAI handles it nicely
    async def wizard_stream():
        data = {
            "id": "chatcmpl-wizard",
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": "jskid-wizard",
            "choices": [{"index": 0, "delta": {"content": response_text}, "finish_reason": None}]
        }
        yield f"data: {json.dumps(data)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(wizard_stream(), media_type="text/event-stream")


# --- Chat Completion Endpoint ---
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_proxy(request: Request):
    global GLOBAL_CONFIG
    # Reload config on every request to catch updates from wizard
    GLOBAL_CONFIG = load_config()

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    # 1. Check if Configured
    if "UPSTREAM_URL" not in GLOBAL_CONFIG:
        return await run_setup_wizard(messages, GLOBAL_CONFIG)

    # 2. Auth Check (if key is set in config)
    proxy_key = GLOBAL_CONFIG.get("PROXY_KEY")
    if proxy_key:
        # Check header or first message for key if not in header (JanitorAI sometimes strips headers)
        auth_header = request.headers.get("Authorization", "")
        # Simple Bearer check or custom header check could go here
        # For this proxy, we assume the config key is for the UPSTREAM API, 
        # OR if you want to protect the PROXY itself, you'd check against a separate env var.
        # Here we assume the Proxy is open once configured, or uses the upstream key.
        pass

    # 3. Initialize Engine
    engine = JSkidCore()
    engine.parse_state(messages)

    # 4. Handle Special Commands (/OP, /OOP, /THEME)
    last_msg_content = messages[-1].get("content", "")
    
    # Theme Switcher Command
    theme_match = re.match(r"^/theme\s+(\w+)", last_msg_content)
    if theme_match:
        new_theme = theme_match.group(1).lower()
        if new_theme in ["cyberpunk", "minimalist", "retro_crt", "brutalist"]:
            engine.ui_theme = new_theme
            # Inject a system message to confirm change visually in next turn
            messages.append({
                "role": "system", 
                "content": f"<!-- [SET_THEME: {new_theme}] --> \n[System: Theme switched to {new_theme}]"
            })

    # 5. Prepare Payload
    clean_msgs = engine.sanitize(messages)
    clean_msgs = engine.inject_world_state(clean_msgs)
    
    payload["messages"] = clean_msgs
    if engine.tools:
        payload["tools"] = engine.tools

    if "stream" not in payload:
        payload["stream"] = True

    # 6. Forward to Upstream
    target_url = GLOBAL_CONFIG["UPSTREAM_URL"]
    headers = {
        "Content-Type": "application/json"
    }
    
    # Pass through Authorization if present, or use stored key if the upstream requires it
    req_auth = request.headers.get("Authorization")
    if req_auth:
        headers["Authorization"] = req_auth
    elif GLOBAL_CONFIG.get("PROXY_KEY"):
        # If the proxy config has a key, assume it's for the upstream
        headers["Authorization"] = f"Bearer {GLOBAL_CONFIG['PROXY_KEY']}"

    client = httpx.AsyncClient(timeout=120.0)
    try:
        req = client.build_request("POST", target_url, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            error_content = await resp.aread()
            return JSONResponse(
                status_code=resp.status_code,
                content={"error": f"Upstream API Error: {resp.status_code}", "details": error_content.decode()}
            )

        # 7. Stream Response with UI Injection
        async def proxy_stream():
            buffer = ""
            in_bracket = False
            ui = AestheticEngine(theme=engine.ui_theme)
            
            # Prepend a small status dashboard to the stream? 
            # Note: JanitorAI might render this as part of the message. 
            # Ideally, this is done in a system message, but for streaming effect:
            
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:]
                
                if data_str == "[DONE]":
                    # Flush buffer
                    if buffer:
                         yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                    
                    # Append a footer dashboard at the end of the stream
                    dashboard = ui.render_status("ONLINE", len(engine.memory), engine.ui_theme)
                    yield f"data: {json.dumps({'choices': [{'delta': {'content': '\n\n' + dashboard}}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                    break

                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0].get("delta", {})
                    if "content" in delta:
                        text = delta["content"]
                        # Simple parser for inline tags to convert them to visible UI elements if desired
                        # For now, we just pass them through, the frontend or next prompt handles them
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': text}}]})}\n\n"
                        
                except json.JSONDecodeError:
                    pass
                    
            await client.aclose()

        return StreamingResponse(proxy_stream(), media_type="text/event-stream")

    except Exception as e:
        await client.aclose()
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "details": str(e)}
        )

@app.get("/")
async def root():
    return {"status": "running", "configured": "UPSTREAM_URL" in GLOBAL_CONFIG}
