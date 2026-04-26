import os
import re
import json
import httpx
import time
import asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

# ==========================================
# 1. CONFIGURATION & STATE MANAGEMENT
# ==========================================
CONFIG_FILE = "jskid_config.json"

def load_config() -> dict:
    """Load config with proper error handling."""
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Config] Load error: {e}")
    return {}

def save_config(config: dict) -> bool:
    """Save config atomically."""
    try:
        with open(CONFIG_FILE + '.tmp', 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        os.replace(CONFIG_FILE + '.tmp', CONFIG_FILE)
        return True
    except Exception as e:
        print(f"[Config] Save error: {e}")
        return False

# Global config cache (refreshed per request)
GLOBAL_CONFIG: dict = {}

# ==========================================
# 2. CHAT-COMPATIBLE UI ENGINE (Fixed Width: 64)
# ==========================================
class AestheticEngine:
    def __init__(self, theme: str = "clean", width: int = 64):
        self.theme = theme
        self.width = max(40, min(120, width))  # Clamp width
        self.chars = {
            "tl": "┌", "tr": "┐", "bl": "└", "br": "┘", 
            "h": "─", "v": "│", "t_left": "├", "t_right": "┤"
        }
        
    def _visual_len(self, text: str) -> int:
        """Get visible length stripping ANSI/control codes."""
        return len(re.sub(r'\x1b\[[0-9;]*m|\[.*?\]', '', text))
    
    def _pad(self, text: str, target_width: int, align: str = "left") -> str:
        """Pad text to exact visual width."""
        visible = self._visual_len(text)
        padding = max(0, target_width - visible)
        if align == "center":
            left, right = padding // 2, padding - (padding // 2)
            return " " * left + text + " " * right
        elif align == "right":
            return " " * padding + text
        return text + " " * padding

    def _wrap_text(self, text: str, max_width: int) -> list:
        """Word-wrap text to fit max_width."""
        if not text:
            return [""]
        words = text.split()
        lines, current = [], ""
        for word in words:
            test = f"{current} {word}".strip()
            if self._visual_len(test) <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def render_box(self, title: str, content_lines: list, width: int = None) -> str:
        """Render a properly-aligned text box."""
        width = width or self.width
        c, iw = self.chars, width - 4  # inner width
        
        # Header with centered title
        title_bar = self._pad(f" {title} ", iw, "center")
        header = f"{c['tl']}{c['h']}{title_bar}{c['h']}{c['tr']}"
        
        # Body with wrapped content
        body = []
        for line in content_lines:
            for wrapped in self._wrap_text(line, iw) if line else [""]:
                padded = self._pad(wrapped, iw, "left")
                body.append(f"{c['v']} {padded} {c['v']}")
        
        # Footer
        footer = f"{c['bl']}{c['h'] * (width - 2)}{c['br']}"
        return "\n".join([header] + body + [footer])

    def render_setup_wizard_step(self, step: int, total: int, message: str, input_hint: str = "") -> str:
        lines = [f"SETUP [{step}/{total}]", "", message]
        if input_hint:
            lines += ["", f"→ {input_hint}"]
        return self.render_box("CONFIGURATION", lines)

    def render_status(self, status: str, memory_count: int, theme_name: str) -> str:
        lines = [f"Status : {status}", f"Memory : {memory_count} items", f"Theme  : {theme_name}", "Proxy  : Active"]
        return self.render_box("JSKID", lines)

    def render_command_list(self, commands: list) -> str:
        lines = ["Commands:"] + [f"  • {c}" for c in commands]
        return self.render_box("HELP", lines)


# ==========================================
# 3. CORE LOGIC & PARSING
# ==========================================
class JSkidCore:
    def __init__(self):
        self.memory: list = []
        self.chars: dict = {}
        self.tools: list = []
        self.ui_theme = "clean"
        self.ui_width = 64

    def parse_state(self, messages: list):
        self.memory.clear()
        self.chars.clear()
        self.tools.clear()
        
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            # Parse custom tags
            tags = re.findall(r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|TOOL|SET_THEME|SET_WIDTH):\s*(.+?)\]\s*-->', content, re.DOTALL)
            for tag_type, val in tags:
                val = val.strip()
                if tag_type == "MEM_ADD" and val and val not in self.memory:
                    self.memory.append(val)
                elif tag_type == "MEM_DEL" and val in self.memory:
                    self.memory.remove(val)
                elif tag_type == "SET_VAR":
                    match = re.match(r'([^=]+)=\s*(.+)', val)
                    if match:
                        k, v = match.groups()
                        self.chars[k.strip()] = v.strip().strip('"\'')
                elif tag_type == "TOOL":
                    try:
                        self.tools.append(json.loads(val))
                    except:
                        pass
                elif tag_type == "SET_THEME" and val.lower() in ["clean", "compact", "spacious"]:
                    self.ui_theme = val.lower()
                elif tag_type == "SET_WIDTH":
                    try:
                        w = int(val)
                        if 40 <= w <= 120:
                            self.ui_width = w
                    except:
                        pass

    def sanitize(self, messages: list) -> list:
        """Remove internal tags and command messages."""
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                clean.append(msg)
                continue
            # Strip tags and previous UI boxes
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'┌[─\s]*┐[\s\S]*?└[─\s]*┘', '', content)
            content = content.strip()
            # Skip user commands
            if msg["role"] == "user" and content.startswith(('/', '!')):
                continue
            if content:
                msg = msg.copy()
                msg["content"] = content
                clean.append(msg)
        return clean

    def inject_world_state(self, messages: list) -> list:
        if not self.memory and not self.chars:
            return messages
        parts = ["\n<world_state>"]
        if self.memory:
            parts.append(f"<mem>{'; '.join(self.memory)}</mem>")
        if self.chars:
            parts.append(f"<vars>{'; '.join(f'{k}={v}' for k,v in self.chars.items())}</vars>")
        parts.append("</world_state>\n")
        ws = "".join(parts)
        # Inject into first system message or prepend
        for msg in messages:
            if msg["role"] == "system":
                msg["content"] += ws
                return messages
        messages.insert(0, {"role": "system", "content": ws.strip()})
        return messages


# ==========================================
# 4. FASTAPI APPLICATION
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    global GLOBAL_CONFIG
    GLOBAL_CONFIG = load_config()
    print(f"✓ JSkid Proxy started | Config: {'loaded' if GLOBAL_CONFIG else 'empty'}")
    yield
    print("✓ JSkid Proxy stopped")

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# --- Setup Wizard (Fixed State Persistence) ---
async def run_setup_wizard(messages: list, config: dict) -> StreamingResponse:
    ui = AestheticEngine(width=64)
    
    # Get last user message content safely
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "").strip()
            break
    
    # Determine step
    has_url = bool(config.get("UPSTREAM_URL", "").strip())
    has_key = "PROXY_KEY" in config  # Can be None if user typed 'skip'
    
    response_text = ""
    
    if not has_url:
        # Step 1: Collect URL
        if last_user_msg and re.match(r'^https?://.+', last_user_msg):
            # Valid URL received - save and advance
            config["UPSTREAM_URL"] = last_user_msg
            if save_config(config):
                global GLOBAL_CONFIG
                GLOBAL_CONFIG = config
                response_text = ui.render_setup_wizard_step(
                    2, 2,
                    "✓ API URL saved.\n\nNext: Enter your API key.\n(Type 'skip' if not required)",
                    "Enter API Key or 'skip'"
                )
            else:
                response_text = ui.render_setup_wizard_step(1, 2, "⚠ Could not save config. Try again.", "Paste URL...")
        else:
            response_text = ui.render_setup_wizard_step(
                1, 2,
                "Welcome to JSkid Proxy!\n\nPaste your upstream API endpoint:\n\nExample:\nhttps://openrouter.ai/api/v1/chat/completions\nhttps://api.openai.com/v1/chat/completions",
                "Paste URL here..."
            )
    elif not has_key:
        # Step 2: Collect API Key
        if last_user_msg:
            key = None if last_user_msg.lower() == "skip" else last_user_msg
            config["PROXY_KEY"] = key
            if save_config(config):
                global GLOBAL_CONFIG
                GLOBAL_CONFIG = config
                status = ui.render_status("READY", 0, "clean")
                help_box = ui.render_command_list(["/theme <name>", "/width <num>", "/reset"])
                response_text = f"{ui.render_setup_wizard_step(2, 2, '✓ Setup complete!', 'Start chatting normally.')}\n\n{status}\n\n{help_box}"
            else:
                response_text = ui.render_setup_wizard_step(2, 2, "⚠ Could not save key. Try again.", "Enter key...")
        else:
            response_text = ui.render_setup_wizard_step(2, 2, "Enter your API key below (or type 'skip'):", "Enter API Key or 'skip'")
    else:
        # Should not reach here, but fallback
        return JSONResponse(content={"error": "Already configured"})
    
    # Stream response in chunks
    async def wizard_stream():
        chunks = [response_text[i:i+120] for i in range(0, len(response_text), 120)]
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            payload = {
                "id": f"wizard-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": "jskid-wizard",
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": "stop" if is_last else None}]
            }
            yield f" {json.dumps(payload)}\n\n"
            if not is_last:
                await asyncio.sleep(0.02)
        yield " [DONE]\n\n"
    
    return StreamingResponse(wizard_stream(), media_type="text/event-stream")


# --- Endpoints ---
@app.get("/")
async def root():
    return {"status": "running", "configured": bool(GLOBAL_CONFIG.get("UPSTREAM_URL"))}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": "jskid-proxy", "object": "model", "owned_by": "jskid", "created": int(time.time())}]}


# --- Chat Completion (Main Handler) ---
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_proxy(request: Request):
    global GLOBAL_CONFIG
    GLOBAL_CONFIG = load_config()  # Refresh config each request
    
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages")
    
    # Run wizard if not configured
    if not GLOBAL_CONFIG.get("UPSTREAM_URL", "").strip():
        return await run_setup_wizard(messages, GLOBAL_CONFIG)
    
    # Initialize engine
    engine = JSkidCore()
    engine.parse_state(messages)
    
    # Handle inline commands
    last_content = messages[-1].get("content", "") if messages else ""
    if last_content.startswith("/status"):
        ui = AestheticEngine(width=engine.ui_width)
        messages.append({"role": "system", "content": ui.render_status("ONLINE", len(engine.memory), engine.ui_theme)})
    elif last_content.startswith("/reset"):
        engine.memory.clear()
        engine.chars.clear()
        messages.append({"role": "system", "content": "[Memory cleared]"})
    
    # Prepare upstream payload
    clean_msgs = engine.sanitize(messages)
    clean_msgs = engine.inject_world_state(clean_msgs)
    payload["messages"] = clean_msgs
    if engine.tools:
        payload["tools"] = engine.tools
    payload.setdefault("stream", True)
    
    # Forward to upstream
    target = GLOBAL_CONFIG["UPSTREAM_URL"]
    headers = {"Content-Type": "application/json"}
    
    # Auth handling
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    elif GLOBAL_CONFIG.get("PROXY_KEY"):
        headers["Authorization"] = f"Bearer {GLOBAL_CONFIG['PROXY_KEY']}"
    
    client = httpx.AsyncClient(timeout=180.0)
    
    try:
        req = client.build_request("POST", target, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(status_code=resp.status_code, content={"error": f"Upstream {resp.status_code}", "details": err.decode()[:400]})
        
        # Stream handler
        async def proxy_stream():
            buffer, count = "", 0
            ui = AestheticEngine(width=engine.ui_width, theme=engine.ui_theme)
            
            async for line in resp.aiter_lines():
                if not line.startswith(" "):
                    continue
                data = line[5:].strip()  # Remove " " prefix
                
                if data == "[DONE]":
                    if buffer.strip():
                        yield f" {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                    # Optional footer for short responses
                    if count < 40:
                        footer = f"\n\n{ui.render_status('OK', len(engine.memory), engine.ui_theme)}"
                        yield f" {json.dumps({'choices': [{'delta': {'content': footer}, 'finish_reason': 'stop'}]})}\n\n"
                    yield " [DONE]\n\n"
                    break
                
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if "content" in delta:
                        text = delta["content"]
                        buffer += text
                        count += 1
                        # Yield periodically for smooth streaming
                        if len(buffer) > 150 or "\n" in text:
                            yield f" {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                            buffer = ""
                except json.JSONDecodeError:
                    continue
        
        return StreamingResponse(proxy_stream(), media_type="text/event-stream")
        
    except httpx.RequestError as e:
        return JSONResponse(status_code=502, content={"error": "Connection failed", "details": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Internal error", "details": str(e)})
    finally:
        await client.aclose()
