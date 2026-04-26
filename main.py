import os
import re
import json
import httpx
import time
from urllib.parse import unquote
from fastapi import FastAPI, Request, HTTPException, Path
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

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

def resolve_upstream(prefix: str) -> str:
    if prefix in UPSTREAM_PRESETS:
        return UPSTREAM_PRESETS[prefix]
    try:
        decoded = unquote(prefix)
        if decoded.startswith("http://") or decoded.startswith("https://"):
            if not decoded.endswith("/chat/completions") and not decoded.endswith("/messages"):
                decoded = decoded.rstrip("/") + "/chat/completions"
            return decoded
    except Exception:
        pass
    return ""


# ==========================================
# 2. CORE ENGINE (Memory/Tags/State)
# ==========================================
class JSkidCore:
    def __init__(self):
        self.memory: list = []
        self.vars: dict = {}
        self.tools: list = []

    def parse(self, messages: list) -> "JSkidCore":
        self.memory.clear()
        self.vars.clear()
        self.tools.clear()
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str):
                continue
            tags = re.findall(
                r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|TOOL):\s*(.+?)\]\s*-->',
                content, re.DOTALL
            )
            for tag, val in tags:
                val = val.strip()
                if tag == "MEM_ADD" and val and val not in self.memory:
                    self.memory.append(val)
                elif tag == "MEM_DEL" and val in self.memory:
                    self.memory.remove(val)
                elif tag == "SET_VAR":
                    m = re.match(r'([^=]+)=\s*(.+)', val)
                    if m:
                        self.vars[m.group(1).strip()] = m.group(2).strip().strip('"\'')
                elif tag == "TOOL":
                    try:
                        self.tools.append(json.loads(val))
                    except Exception:
                        pass
        return self

    def sanitize(self, messages: list) -> list:
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL).strip()
                if msg["role"] == "user" and content.startswith(('/', '!')):
                    continue
            if content or msg["role"] != "user":
                new_msg = msg.copy()
                new_msg["content"] = content if isinstance(content, str) else msg.get("content")
                clean.append(new_msg)
        return clean

    def inject_state(self, messages: list) -> list:
        if not self.memory and not self.vars:
            return messages
        parts = ["\n<hidden_context>"]
        if self.memory:
            parts.append(f"Memory: {'; '.join(self.memory)}")
        if self.vars:
            parts.append(f"Variables: {'; '.join(f'{k}={v}' for k,v in self.vars.items())}")
        parts.append("</hidden_context>\n")
        state = "".join(parts)
        for msg in messages:
            if msg["role"] == "system":
                msg["content"] = msg.get("content", "") + state
                return messages
        messages.insert(0, {"role": "system", "content": state.strip()})
        return messages


# ==========================================
# 3. UI ENGINE (for /status command)
# ==========================================
class UIEngine:
    def __init__(self, width: int = 64):
        self.width = width
        self.chars = {"tl": "┌", "tr": "┐", "bl": "└", "br": "┘", "h": "─", "v": "│"}

    def render_box(self, title: str, lines: list) -> str:
        inner = self.width - 4
        title_pad = " " * max(0, (inner - len(title)) // 2) + f" {title} "
        header = f"{self.chars['tl']}{self.chars['h']}{title_pad.ljust(inner)}{self.chars['h']}{self.chars['tr']}"
        body = [f"{self.chars['v']} {line.ljust(inner)} {self.chars['v']}" for line in lines]
        footer = f"{self.chars['bl']}{self.chars['h']*(self.width-2)}{self.chars['br']}"
        return "\n".join([header] + body + [footer])


# ==========================================
# 4. FASTAPI APPLICATION
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✓ JSkid Proxy started")
    yield
    print("✓ JSkid Proxy stopped")

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {
        "status": "running",
        "presets": list(UPSTREAM_PRESETS.keys()),
        "usage": "API URL: https://jskid.onrender.com/{preset}/v1"
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "jskid-proxy", "object": "model", "owned_by": "jskid", "created": int(time.time())}]
    }


# ==========================================
# 5. CHAT PROXY - ROBUST STREAMING
# ==========================================
@app.post("/{prefix}/v1/chat/completions")
@app.post("/{prefix}/chat/completions")
async def proxy(request: Request, prefix: str = Path(...)):
    upstream_url = resolve_upstream(prefix)
    if not upstream_url:
        raise HTTPException(400, detail=f"Unknown preset: {prefix}. Use: {list(UPSTREAM_PRESETS.keys())}")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, detail="Invalid JSON")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(400, detail="No messages")

    core = JSkidCore().parse(messages)

    # Handle /status command locally
    last_msg = messages[-1].get("content", "") if messages else ""
    if last_msg.startswith("/status"):
        ui = UIEngine()
        box = ui.render_box("JSKID PROXY", [
            f"Upstream : {prefix}",
            f"Memory   : {len(core.memory)} facts",
            f"Variables: {len(core.vars)} active",
            "Status   : ✓ Online"
        ])
        return JSONResponse(content={
            "choices": [{"message": {"role": "assistant", "content": box}}],
            "finish_reason": "stop"
        })

    clean_msgs = core.sanitize(messages)
    clean_msgs = core.inject_state(clean_msgs)
    body["messages"] = clean_msgs
    if core.tools:
        body["tools"] = core.tools
    body.setdefault("stream", True)

    # Headers for upstream
    headers = {"Content-Type": "application/json"}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    for h in ["x-api-key", "http-referer", "x-title", "user-agent"]:
        if request.headers.get(h):
            headers[h] = request.headers[h]

    # Client with generous timeouts for Render free tier
    client = httpx.AsyncClient(
        timeout=httpx.Timeout(300.0, connect=30.0, read=300.0, write=30.0),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
    )

    try:
        req = client.build_request("POST", upstream_url, json=body, headers=headers)
        resp = await client.send(req, stream=True)

        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(
                resp.status_code,
                content={"error": f"Upstream {resp.status_code}", "details": err.decode()[:300] if err else ""}
            )

        # Stream with robust error handling
        async def stream_proxy():
            try:
                async for line in resp.aiter_lines():
                    # Pass through SSE lines exactly as received
                    if line.strip():
                        yield f"{line}\n\n"
            except (httpx.ReadError, httpx.ConnectError, httpx.ReadTimeout) as e:
                # Connection issue - send graceful finish
                print(f"[Stream interrupted] {type(e).__name__}")
                yield ' {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n'
                yield " [DONE]\n\n"
            except asyncio.CancelledError:
                pass
            except Exception as e:
                print(f"[Stream error] {e}")
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(stream_proxy(), media_type="text/event-stream")

    except httpx.ConnectError:
        return JSONResponse(502, content={"error": "Cannot connect to upstream", "upstream": upstream_url[:50]})
    except httpx.ReadTimeout:
        return JSONResponse(504, content={"error": "Upstream timeout", "upstream": upstream_url[:50]})
    except httpx.RequestError as e:
        return JSONResponse(502, content={"error": "Connection failed", "details": str(e)[:150]})
    except Exception as e:
        print(f"[Proxy error] {type(e).__name__}: {e}")
        return JSONResponse(500, content={"error": "Internal error", "details": str(e)[:150]})


# ==========================================
# 6. FALLBACK ENDPOINT (no path prefix)
# ==========================================
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def fallback_proxy(request: Request):
    """Fallback for clients using standard endpoint."""
    upstream = os.getenv("UPSTREAM_URL", "https://openrouter.ai/api/v1/chat/completions")
    
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, detail="Invalid JSON")
    
    body.setdefault("stream", True)
    headers = {"Content-Type": "application/json"}
    auth = request.headers.get("Authorization")
    if auth:
        headers["Authorization"] = auth
    
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    try:
        req = client.build_request("POST", upstream, json=body, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(resp.status_code, content={"error": f"Upstream {resp.status_code}"})
        
        async def stream():
            async for line in resp.aiter_lines():
                if line.strip():
                    yield f"{line}\n\n"
            await client.aclose()
        
        return StreamingResponse(stream(), media_type="text/event-stream")
    except Exception as e:
        return JSONResponse(502, content={"error": str(e)[:200]})
    finally:
        await client.aclose()
