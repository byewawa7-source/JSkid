import os
import re
import json
import httpx
import time
import asyncio
from urllib.parse import unquote
from fastapi import FastAPI, Request, HTTPException, Path
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from typing import Dict, Any, List, Optional

# ==========================================
# 1. UPSTREAM URL MAPPING
# ==========================================
# Preset shortcuts: /openrouter, /openai, /anthropic, etc.
UPSTREAM_PRESETS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
}

def resolve_upstream_url(path_prefix: str) -> str:
    """
    Resolve upstream URL from path prefix.
    Supports:
    - Presets: /openrouter → https://openrouter.ai/api/v1/chat/completions
    - Full URL: /https%3A%2F%2Fcustom.com%2Fv1 → decoded custom URL
    """
    # Check presets first
    if path_prefix in UPSTREAM_PRESETS:
        return UPSTREAM_PRESETS[path_prefix]
    
    # Try to decode as URL-encoded full URL
    try:
        decoded = unquote(path_prefix)
        if decoded.startswith("http://") or decoded.startswith("https://"):
            # Ensure it ends with chat completions endpoint
            if not decoded.endswith("/chat/completions") and not decoded.endswith("/messages"):
                decoded = decoded.rstrip("/") + "/chat/completions"
            return decoded
    except:
        pass
    
    return ""


# ==========================================
# 2. CHAT-COMPATIBLE UI ENGINE (64 chars wide)
# ==========================================
class AestheticEngine:
    def __init__(self, theme: str = "clean", width: int = 64):
        self.theme = theme
        self.width = max(40, min(120, width))
        self.chars = {
            "tl": "┌", "tr": "┐", "bl": "└", "br": "┘", 
            "h": "─", "v": "│", "t_left": "├", "t_right": "┤"
        }
        
    def _visual_len(self, text: str) -> int:
        return len(re.sub(r'\x1b\[[0-9;]*m|\[.*?\]', '', text))
    
    def _pad(self, text: str, target_width: int, align: str = "left") -> str:
        visible = self._visual_len(text)
        padding = max(0, target_width - visible)
        if align == "center":
            left, right = padding // 2, padding - (padding // 2)
            return " " * left + text + " " * right
        elif align == "right":
            return " " * padding + text
        return text + " " * padding

    def _wrap_text(self, text: str, max_width: int) -> list:
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
        width = width or self.width
        c, iw = self.chars, width - 4
        title_bar = self._pad(f" {title} ", iw, "center")
        header = f"{c['tl']}{c['h']}{title_bar}{c['h']}{c['tr']}"
        body = []
        for line in content_lines:
            for wrapped in self._wrap_text(line, iw) if line else [""]:
                padded = self._pad(wrapped, iw, "left")
                body.append(f"{c['v']} {padded} {c['v']}")
        footer = f"{c['bl']}{c['h'] * (width - 2)}{c['br']}"
        return "\n".join([header] + body + [footer])

    def render_status(self, upstream: str, memory_count: int, theme_name: str) -> str:
        # Truncate upstream for display
        display_url = re.sub(r'^https?://(?:www\.)?', '', upstream)
        if len(display_url) > 25:
            display_url = display_url[:22] + "..."
        lines = [
            f"Upstream: {display_url}",
            f"Memory  : {memory_count} items", 
            f"Theme   : {theme_name}",
            f"Status  : ✓ Active"
        ]
        return self.render_box("JSKID PROXY", lines)

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
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                clean.append(msg)
                continue
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'┌[─\s]*┐[\s\S]*?└[─\s]*┘', '', content)
            content = content.strip()
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
    print("✓ JSkid Proxy started | URL-from-path mode")
    yield
    print("✓ JSkid Proxy stopped")

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# --- Endpoints ---
@app.get("/")
async def root():
    return {
        "status": "running",
        "mode": "url-from-path",
        "presets": list(UPSTREAM_PRESETS.keys()),
        "usage": "Set JanitorAI API URL to: https://your-proxy.com/{preset}\nSet JanitorAI API Key to: your-actual-llm-key"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": "jskid-proxy", "object": "model", "owned_by": "jskid", "created": int(time.time())}]}


# --- Chat Completion (Main Handler) ---
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
@app.post("/{path_prefix}/v1/chat/completions")
@app.post("/{path_prefix}/chat/completions")
async def chat_proxy(
    request: Request, 
    path_prefix: str = Path(..., description="Upstream preset or URL-encoded endpoint")
):
    # Resolve upstream URL from path
    upstream_url = resolve_upstream_url(path_prefix)
    if not upstream_url:
        raise HTTPException(
            status_code=400, 
            detail=f"Unknown upstream: '{path_prefix}'. Use one of: {list(UPSTREAM_PRESETS.keys())} or a URL-encoded full URL"
        )
    
    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    # Initialize engine
    engine = JSkidCore()
    engine.parse_state(messages)
    
    # Handle inline commands
    last_content = messages[-1].get("content", "") if messages else ""
    if last_content.startswith("/status"):
        ui = AestheticEngine(width=engine.ui_width)
        messages.append({"role": "system", "content": ui.render_status(upstream_url, len(engine.memory), engine.ui_theme)})
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
    
    # Forward to upstream with client's auth header
    headers = {"Content-Type": "application/json"}
    
    # Pass through Authorization header (this is the user's actual LLM API key)
    auth_header = request.headers.get("Authorization")
    if auth_header:
        headers["Authorization"] = auth_header
    
    # Also copy other useful headers
    for h in ["x-api-key", "http-referer", "x-title"]:
        if request.headers.get(h):
            headers[h] = request.headers[h]
    
    client = httpx.AsyncClient(timeout=180.0)
    
    try:
        req = client.build_request("POST", upstream_url, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(
                status_code=resp.status_code, 
                content={"error": f"Upstream {resp.status_code}", "details": err.decode()[:400]}
            )
        
        # Stream handler with optional UI footer
        async def proxy_stream():
            buffer, count = "", 0
            ui = AestheticEngine(width=engine.ui_width, theme=engine.ui_theme)
            
            async for line in resp.aiter_lines():
                # Handle both "data: " and " " prefixes
                if line.startswith("data: "):
                    data = line[6:].strip()
                elif line.startswith(" "):
                    data = line[5:].strip()
                else:
                    continue
                
                if data == "[DONE]":
                    if buffer.strip():
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                    # Optional footer for short responses
                    if count < 40:
                        footer = f"\n\n{ui.render_status(upstream_url, len(engine.memory), engine.ui_theme)}"
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': footer}, 'finish_reason': 'stop'}]})}\n\n"
                    yield "data: [DONE]\n\n"
                    break
                
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if "content" in delta:
                        text = delta["content"]
                        buffer += text
                        count += 1
                        if len(buffer) > 150 or "\n" in text:
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
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
