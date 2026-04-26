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
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_config(config: dict):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

GLOBAL_CONFIG = load_config()

# ==========================================
# 2. CHAT-COMPATIBLE UI ENGINE (64 chars wide)
# ==========================================
class AestheticEngine:
    def __init__(self, theme: str = "clean", width: int = 64):
        self.theme = theme
        self.width = width
        self.chars = {
            "tl": "┌", "tr": "┐", "bl": "└", "br": "┘", 
            "h": "─", "v": "│", "t_left": "├", "t_right": "┤"
        }
        
    def _visual_len(self, text: str) -> int:
        clean = re.sub(r'\x1b\[[0-9;]*m', '', text)
        return len(clean)
    
    def _pad(self, text: str, width: int, align: str = "left") -> str:
        visible_len = self._visual_len(text)
        padding_needed = max(0, width - visible_len)
        if align == "center":
            left = padding_needed // 2
            right = padding_needed - left
            return " " * left + text + " " * right
        elif align == "right":
            return " " * padding_needed + text
        return text + " " * padding_needed

    def _wrap_text(self, text: str, max_width: int) -> list:
        if not text:
            return [""]
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = current + (" " if current else "") + word
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
        if width is None:
            width = self.width
        c = self.chars
        inner_width = width - 4
        title_display = f" {title} "
        title_padded = self._pad(title_display, width - 4, "center")
        header = f"{c['tl']}{c['h'] * 2}{title_padded}{c['h'] * 2}{c['tr']}"
        body = []
        for line in content_lines:
            wrapped = self._wrap_text(line, inner_width) if line else [""]
            for wrapped_line in wrapped:
                padded = self._pad(wrapped_line, inner_width, "left")
                body.append(f"{c['v']} {padded} {c['v']}")
        footer = f"{c['bl']}{c['h'] * (width - 2)}{c['br']}"
        return "\n".join([header] + body + [footer])

    def render_setup_wizard_step(self, step: int, total: int, message: str, input_hint: str = "") -> str:
        lines = [f"SETUP [{step}/{total}]", "", message]
        if input_hint:
            lines.append("")
            lines.append(f"→ {input_hint}")
        return self.render_box("CONFIGURATION", lines)

    def render_status(self, status: str, memory_count: int, theme_name: str) -> str:
        lines = [
            f"Status  : {status}",
            f"Memory  : {memory_count} items",
            f"Theme   : {theme_name}",
            f"Proxy   : Active"
        ]
        return self.render_box("JSKID", lines)

    def render_command_list(self, commands: list) -> str:
        lines = ["Commands:"]
        for cmd in commands:
            lines.append(f"  • {cmd}")
        return self.render_box("HELP", lines)


# ==========================================
# 3. CORE LOGIC & PARSING
# ==========================================
class JSkidCore:
    def __init__(self):
        self.memory = []
        self.chars = {}
        self.tools = []
        self.ui_theme = "clean"
        self.ui_width = 64

    def parse_state(self, messages):
        self.memory.clear()
        self.chars.clear()
        self.tools.clear()
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): 
                continue
            tags = re.findall(
                r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|EXT|TOOL|SET_THEME|SET_WIDTH):\s*(.*?)]\s*-->', 
                content, re.DOTALL
            )
            for tag_type, val in tags:
                val = val.strip()
                if tag_type == "MEM_ADD" and val and val not in self.memory:
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
                    except: 
                        pass
                elif tag_type == "SET_THEME":
                    if val.lower() in ["clean", "compact", "spacious"]:
                        self.ui_theme = val.lower()
                elif tag_type == "SET_WIDTH":
                    try:
                        w = int(val)
                        if 40 <= w <= 120:
                            self.ui_width = w
                    except:
                        pass

    def sanitize(self, messages):
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                clean.append(msg)
                continue
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'┌[─\s]*┐[\s\S]*?└[─\s]*┘', '', content)
            content = content.strip()
            if msg["role"] == "user" and content.startswith(('/', '!')):
                continue
            if content:
                msg["content"] = content
                clean.append(msg)
        return clean

    def inject_world_state(self, messages):
        if not self.memory and not self.chars:
            return messages
        ws_parts = ["\n<world_state>"]
        if self.memory:
            ws_parts.append(f"<mem>{'; '.join(self.memory)}</mem>")
        if self.chars:
            ws_parts.append(f"<vars>{'; '.join(f'{k}={v}' for k, v in self.chars.items())}</vars>")
        ws_parts.append("</world_state>\n")
        ws_text = "".join(ws_parts)
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


# --- Setup Wizard ---
async def run_setup_wizard(messages: list, current_config: dict) -> StreamingResponse:
    ui = AestheticEngine(width=64)
    last_msg = messages[-1].get("content", "").strip() if messages else ""
    
    step = 1
    if "UPSTREAM_URL" in current_config:
        step = 2
    if "PROXY_KEY" in current_config:
        step = 3

    if step == 3:
        return JSONResponse(content={"error": "Already configured"})

    response_text = ""
    
    if step == 1:
        if last_msg and (last_msg.startswith("http://") or last_msg.startswith("https://")):
            current_config["UPSTREAM_URL"] = last_msg.strip()
            save_config(current_config)
            response_text = ui.render_setup_wizard_step(
                2, 2, 
                "✓ API URL saved.\n\nNext: Enter your API key below.\n(Type 'skip' if none required)", 
                "Enter API Key or 'skip'"
            )
        else:
            response_text = ui.render_setup_wizard_step(
                1, 2,
                "Welcome to JSkid Proxy!\n\nPaste your upstream API endpoint:\n\nExample:\nhttps://api.openai.com/v1/chat/completions",
                "Paste URL here..."
            )
    elif step == 2:
        key = last_msg.strip() if last_msg.strip().lower() != "skip" else None
        current_config["PROXY_KEY"] = key
        save_config(current_config)
        status_box = ui.render_status("READY", 0, "clean")
        help_box = ui.render_command_list([
            "/theme <name>  - Change UI style",
            "/width <num>   - Adjust width",
            "/reset         - Clear memory"
        ])
        response_text = f"{ui.render_setup_wizard_step(2, 2, '✓ Setup complete!', 'Start chatting.')}\n\n{status_box}\n\n{help_box}"

    async def wizard_stream():
        # CRITICAL: Use "data: " prefix for SSE compatibility
        chunks = [response_text[i:i+150] for i in range(0, len(response_text), 150)]
        for i, chunk in enumerate(chunks):
            is_last = (i == len(chunks) - 1)
            chunk_data = {
                "id": "chatcmpl-wizard",
                "object": "chat.completion.chunk", 
                "created": int(time.time()),
                "model": "jskid-wizard",
                "choices": [{
                    "index": 0, 
                    "delta": {"content": chunk}, 
                    "finish_reason": "stop" if is_last else None
                }]
            }
            # FIX: Proper SSE format with "data: " prefix
            yield f"data: {json.dumps(chunk_data)}\n\n"
            if not is_last:
                await asyncio.sleep(0.01)
        # FIX: Proper [DONE] format
        yield "data: [DONE]\n\n"

    return StreamingResponse(wizard_stream(), media_type="text/event-stream")


# --- Endpoints ---
@app.get("/")
async def root():
    config = load_config()
    return {"status": "running", "configured": "UPSTREAM_URL" in config}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "jskid-proxy", "object": "model", "owned_by": "jskid", "created": int(time.time())}]
    }


# --- Chat Completion ---
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_proxy(request: Request):
    global GLOBAL_CONFIG
    GLOBAL_CONFIG = load_config()

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    if "UPSTREAM_URL" not in GLOBAL_CONFIG:
        return await run_setup_wizard(messages, GLOBAL_CONFIG)

    engine = JSkidCore()
    engine.parse_state(messages)

    last_msg_content = messages[-1].get("content", "")
    if last_msg_content.startswith("/status"):
        ui = AestheticEngine(width=engine.ui_width)
        messages.append({"role": "system", "content": ui.render_status("ONLINE", len(engine.memory), engine.ui_theme)})
    if last_msg_content.startswith("/reset"):
        engine.memory.clear()
        engine.chars.clear()
        messages.append({"role": "system", "content": "[Memory cleared]"})

    clean_msgs = engine.sanitize(messages)
    clean_msgs = engine.inject_world_state(clean_msgs)
    
    payload["messages"] = clean_msgs
    if engine.tools:
        payload["tools"] = engine.tools
    if "stream" not in payload:
        payload["stream"] = True

    target_url = GLOBAL_CONFIG["UPSTREAM_URL"]
    headers = {"Content-Type": "application/json"}
    
    req_auth = request.headers.get("Authorization")
    if req_auth:
        headers["Authorization"] = req_auth
    elif GLOBAL_CONFIG.get("PROXY_KEY"):
        headers["Authorization"] = f"Bearer {GLOBAL_CONFIG['PROXY_KEY']}"

    client = httpx.AsyncClient(timeout=180.0)
    
    try:
        req = client.build_request("POST", target_url, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            error_content = await resp.aread()
            return JSONResponse(
                status_code=resp.status_code,
                content={"error": f"Upstream Error {resp.status_code}", "details": error_content.decode()[:500]}
            )

        async def proxy_stream():
            buffer = ""
            ui = AestheticEngine(width=engine.ui_width, theme=engine.ui_theme)
            chunk_count = 0
            
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()  # Remove "data: " prefix from upstream
                
                if data_str == "[DONE]":
                    if buffer.strip():
                        # FIX: Proper SSE format
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                    
                    # Optional footer
                    if chunk_count < 50:
                        footer = f"\n\n{ui.render_status('OK', len(engine.memory), engine.ui_theme)}"
                        finish_payload = {"choices": [{"delta": {"content": footer}, "finish_reason": "stop"}]}
                        yield f"data: {json.dumps(finish_payload)}\n\n"
                    
                    # FIX: Proper [DONE] format
                    yield "data: [DONE]\n\n"
                    break

                try:
                    data = json.loads(data_str)
                    delta = data["choices"][0].get("delta", {})
                    if "content" in delta:
                        text = delta["content"]
                        buffer += text
                        chunk_count += 1
                        if len(buffer) > 200 or "\n" in text:
                            # FIX: Proper SSE format
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                            buffer = ""
                except json.JSONDecodeError:
                    continue
                    
        return StreamingResponse(proxy_stream(), media_type="text/event-stream")

    except httpx.RequestError as e:
        return JSONResponse(status_code=502, content={"error": "Connection Failed", "details": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": "Internal Error", "details": str(e)})
    finally:
        await client.aclose()
