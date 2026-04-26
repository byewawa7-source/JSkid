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
UPSTREAM_PRESETS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "openai": "https://api.openai.com/v1/chat/completions",
    "anthropic": "https://api.anthropic.com/v1/messages",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    "together": "https://api.together.xyz/v1/chat/completions",
    "deepseek": "https://api.deepseek.com/v1/chat/completions",
}

def resolve_upstream_url(path_prefix: str) -> str:
    if path_prefix in UPSTREAM_PRESETS:
        return UPSTREAM_PRESETS[path_prefix]
    try:
        decoded = unquote(path_prefix)
        if decoded.startswith("http://") or decoded.startswith("https://"):
            if not decoded.endswith("/chat/completions") and not decoded.endswith("/messages"):
                decoded = decoded.rstrip("/") + "/chat/completions"
            return decoded
    except:
        pass
    return ""


# ==========================================
# 2. UI ENGINE (64 chars, chat-compatible)
# ==========================================
class AestheticEngine:
    def __init__(self, theme: str = "clean", width: int = 64):
        self.theme = theme
        self.width = max(40, min(120, width))
        self.chars = {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"}
        
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
        if not text: return [""]
        words, lines, current = text.split(), [], ""
        for word in words:
            test = f"{current} {word}".strip()
            if self._visual_len(test) <= max_width:
                current = test
            else:
                if current: lines.append(current)
                current = word
        if current: lines.append(current)
        return lines

    def render_box(self, title: str, content_lines: list, width: int = None) -> str:
        width = width or self.width
        c, iw = self.chars, width - 4
        title_bar = self._pad(f" {title} ", iw, "center")
        header = f"{c['tl']}{c['h']}{title_bar}{c['h']}{c['tr']}"
        body = []
        for line in content_lines:
            for wrapped in self._wrap_text(line, iw) if line else [""]:
                body.append(f"{c['v']} {self._pad(wrapped, iw)} {c['v']}")
        footer = f"{c['bl']}{c['h'] * (width - 2)}{c['br']}"
        return "\n".join([header] + body + [footer])

    def render_status(self, upstream: str, memory_count: int, theme_name: str) -> str:
        display = re.sub(r'^https?://(?:www\.)?', '', upstream)
        if len(display) > 22: display = display[:19] + "..."
        return self.render_box("JSKID", [f"Upstream: {display}", f"Memory: {memory_count}", f"Theme: {theme_name}", "Status: ✓"])


# ==========================================
# 3. CORE LOGIC
# ==========================================
class JSkidCore:
    def __init__(self):
        self.memory, self.chars, self.tools = [], {}, []
        self.ui_theme, self.ui_width = "clean", 64

    def parse_state(self, messages: list):
        self.memory.clear(); self.chars.clear(); self.tools.clear()
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): continue
            tags = re.findall(r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|TOOL|SET_THEME|SET_WIDTH):\s*(.+?)\]\s*-->', content, re.DOTALL)
            for tag_type, val in tags:
                val = val.strip()
                if tag_type == "MEM_ADD" and val and val not in self.memory: self.memory.append(val)
                elif tag_type == "MEM_DEL" and val in self.memory: self.memory.remove(val)
                elif tag_type == "SET_VAR":
                    m = re.match(r'([^=]+)=\s*(.+)', val)
                    if m: self.chars[m.group(1).strip()] = m.group(2).strip().strip('"\'')
                elif tag_type == "TOOL":
                    try: self.tools.append(json.loads(val))
                    except: pass
                elif tag_type == "SET_THEME" and val.lower() in ["clean","compact","spacious"]: self.ui_theme = val.lower()
                elif tag_type == "SET_WIDTH":
                    try:
                        w = int(val)
                        if 40 <= w <= 120: self.ui_width = w
                    except: pass

    def sanitize(self, messages: list) -> list:
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): clean.append(msg); continue
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'┌[─\s]*┐[\s\S]*?└[─\s]*┘', '', content)
            content = content.strip()
            if msg["role"] == "user" and content.startswith(('/', '!')): continue
            if content: msg = msg.copy(); msg["content"] = content; clean.append(msg)
        return clean

    def inject_world_state(self, messages: list) -> list:
        if not self.memory and not self.chars: return messages
        parts = ["\n<world_state>"]
        if self.memory: parts.append(f"<mem>{'; '.join(self.memory)}</mem>")
        if self.chars: parts.append(f"<vars>{'; '.join(f'{k}={v}' for k,v in self.chars.items())}</vars>")
        parts.append("</world_state>\n")
        ws = "".join(parts)
        for msg in messages:
            if msg["role"] == "system": msg["content"] += ws; return messages
        messages.insert(0, {"role": "system", "content": ws.strip()})
        return messages


# ==========================================
# 4. FASTAPI APP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✓ JSkid Proxy started")
    yield

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "running", "presets": list(UPSTREAM_PRESETS.keys()), "usage": "API URL: https://jskid.onrender.com/{preset}/v1"}

@app.get("/health")
async def health(): return {"status": "healthy"}

@app.get("/v1/models")
async def list_models():
    return {"object": "list", "data": [{"id": "jskid-proxy", "object": "model", "owned_by": "jskid", "created": int(time.time())}]}


# ==========================================
# 5. CHAT COMPLETION - FIXED SSE FORMAT
# ==========================================
@app.post("/{path_prefix}/v1/chat/completions")
@app.post("/{path_prefix}/chat/completions")
async def chat_proxy(request: Request, path_prefix: str = Path(...)):
    upstream_url = resolve_upstream_url(path_prefix)
    if not upstream_url:
        raise HTTPException(400, detail=f"Unknown preset: {path_prefix}. Use: {list(UPSTREAM_PRESETS.keys())}")
    
    try: payload = await request.json()
    except json.JSONDecodeError: raise HTTPException(400, detail="Invalid JSON")
    
    messages = payload.get("messages", [])
    if not messages: raise HTTPException(400, detail="No messages")
    
    engine = JSkidCore()
    engine.parse_state(messages)
    
    # Handle commands
    last = messages[-1].get("content", "") if messages else ""
    if last.startswith("/status"):
        messages.append({"role": "system", "content": AestheticEngine(width=engine.ui_width).render_status(upstream_url, len(engine.memory), engine.ui_theme)})
    elif last.startswith("/reset"):
        engine.memory.clear(); engine.chars.clear()
        messages.append({"role": "system", "content": "[Memory cleared]"})
    
    clean_msgs = engine.sanitize(messages)
    clean_msgs = engine.inject_world_state(clean_msgs)
    payload["messages"] = clean_msgs
    if engine.tools: payload["tools"] = engine.tools
    payload.setdefault("stream", True)
    
    # Forward request
    headers = {"Content-Type": "application/json"}
    auth = request.headers.get("Authorization")
    if auth: headers["Authorization"] = auth
    elif os.getenv("DEFAULT_API_KEY"): headers["Authorization"] = f"Bearer {os.getenv('DEFAULT_API_KEY')}"
    
    client = httpx.AsyncClient(timeout=180.0)
    
    try:
        req = client.build_request("POST", upstream_url, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(resp.status_code, content={"error": f"Upstream {resp.status_code}", "details": err.decode()[:300]})
        
        # === CRITICAL: SSE STREAMING WITH CORRECT FORMAT ===
        async def proxy_stream():
            ui = AestheticEngine(width=engine.ui_width, theme=engine.ui_theme)
            buffer, count = "", 0
            
            async for line in resp.aiter_lines():
                # Skip empty lines
                if not line.strip(): continue
                
                # Handle OpenAI-style SSE: "data: {...}" or " {...}"
                if line.startswith("data: "):
                    data = line[6:].strip()
                elif line.startswith(" "):
                    data = line[5:].strip()
                else:
                    continue
                
                if data == "[DONE]":
                    # Flush buffer
                    if buffer.strip():
                        # ✅ CORRECT FORMAT: space + JSON + double newline
                        yield f" {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                    # Optional footer
                    if count < 30:
                        footer = f"\n\n{ui.render_status(upstream_url, len(engine.memory), engine.ui_theme)}"
                        yield f" {json.dumps({'choices': [{'delta': {'content': footer}, 'finish_reason': 'stop'}]})}\n\n"
                    # ✅ CORRECT DONE FORMAT
                    yield " [DONE]\n\n"
                    break
                
                try:
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if "content" in delta:
                        text = delta["content"]
                        buffer += text
                        count += 1
                        # Yield chunks for smooth streaming
                        if len(buffer) > 100 or "\n" in text:
                            yield f" {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                            buffer = ""
                except json.JSONDecodeError:
                    continue
            
            await client.aclose()
        
        return StreamingResponse(proxy_stream(), media_type="text/event-stream")
        
    except httpx.RequestError as e:
        return JSONResponse(502, content={"error": "Connection failed", "details": str(e)})
    except Exception as e:
        return JSONResponse(500, content={"error": "Internal error", "details": str(e)})
    finally:
        await client.aclose()
