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
    except:
        pass
    return ""


# ==========================================
# 2. CORE ENGINE
# ==========================================
class JSkidCore:
    def __init__(self):
        self.memory, self.vars, self.tools = [], {}, []

    def parse(self, messages):
        self.memory.clear(); self.vars.clear(); self.tools.clear()
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): continue
            for tag, val in re.findall(r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|TOOL):\s*(.+?)\]\s*-->', content, re.DOTALL):
                val = val.strip()
                if tag == "MEM_ADD" and val and val not in self.memory: self.memory.append(val)
                elif tag == "MEM_DEL" and val in self.memory: self.memory.remove(val)
                elif tag == "SET_VAR":
                    m = re.match(r'([^=]+)=\s*(.+)', val)
                    if m: self.vars[m.group(1).strip()] = m.group(2).strip().strip('"\'')
                elif tag == "TOOL":
                    try: self.tools.append(json.loads(val))
                    except: pass
        return self

    def sanitize(self, messages):
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL).strip()
                if msg["role"] == "user" and content.startswith(('/', '!')): continue
            if content or msg["role"] != "user":
                new = msg.copy(); new["content"] = content if isinstance(content, str) else msg.get("content"); clean.append(new)
        return clean

    def inject_state(self, messages):
        if not self.memory and not self.vars: return messages
        parts = ["\n<hidden_context>"]
        if self.memory: parts.append(f"Memory: {'; '.join(self.memory)}")
        if self.vars: parts.append(f"Variables: {'; '.join(f'{k}={v}' for k,v in self.vars.items())}")
        parts.append("</hidden_context>\n")
        state = "".join(parts)
        for msg in messages:
            if msg["role"] == "system": msg["content"] = msg.get("content", "") + state; return messages
        messages.insert(0, {"role": "system", "content": state.strip()})
        return messages


# ==========================================
# 3. UI ENGINE
# ==========================================
class UIEngine:
    def __init__(self, width=64):
        self.width, self.c = width, {"tl":"┌","tr":"┐","bl":"└","br":"┘","h":"─","v":"│"}
    def box(self, title, lines):
        iw = self.width - 4
        hdr = f"{self.c['tl']}{self.c['h']}{(' '*(iw-len(title))//2)} {title} {self.c['h']*(iw-((iw-len(title))//2)-len(title)-1)}{self.c['tr']}"
        body = [f"{self.c['v']} {l.ljust(iw)} {self.c['v']}" for l in lines]
        return "\n".join([hdr] + body + [f"{self.c['bl']}{self.c['h']*(self.width-2)}{self.c['br']}"])


# ==========================================
# 4. FASTAPI APP
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("✓ JSkid Proxy started")
    yield
    print("✓ JSkid Proxy stopped")

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status":"running","presets":list(UPSTREAM_PRESETS.keys()),"usage":"API URL: https://jskid.onrender.com/{preset}/v1"}

@app.get("/health")
async def health(): return {"status":"healthy"}

@app.get("/v1/models")
async def models():
    return {"object":"list","data":[{"id":"jskid","object":"model","owned_by":"jskid","created":int(time.time())}]}


# ==========================================
# 5. ULTRA-ROBUST PROXY (Raw byte streaming)
# ==========================================
@app.post("/{prefix}/v1/chat/completions")
@app.post("/{prefix}/chat/completions")
async def proxy(request: Request, prefix: str = Path(...)):
    upstream = resolve_upstream(prefix)
    if not upstream:
        raise HTTPException(400, detail=f"Unknown: {prefix}. Use: {list(UPSTREAM_PRESETS.keys())}")

    try: body = await request.json()
    except: raise HTTPException(400, detail="Invalid JSON")

    messages = body.get("messages", [])
    if not messages: raise HTTPException(400, detail="No messages")

    core = JSkidCore().parse(messages)

    # /status command
    if (messages[-1].get("content","") if messages else "").startswith("/status"):
        ui = UIEngine()
        return JSONResponse({"choices":[{"message":{"role":"assistant","content":ui.box("JSKID",[f"Upstream:{prefix}",f"Memory:{len(core.memory)}",f"Vars:{len(core.vars)}","Status:✓"])}}],"finish_reason":"stop"})

    clean = core.sanitize(messages)
    clean = core.inject_state(clean)
    body["messages"] = clean
    if core.tools: body["tools"] = core.tools
    body.setdefault("stream", True)

    headers = {"Content-Type":"application/json"}
    auth = request.headers.get("Authorization")
    if auth: headers["Authorization"] = auth
    for h in ["x-api-key","http-referer","x-title"]:
        if request.headers.get(h): headers[h] = request.headers[h]

    # === CRITICAL: Raw byte streaming with retry ===
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0, read=300.0, write=30.0))

    try:
        # Retry once on connection failure (Render wake-up)
        for attempt in range(2):
            try:
                resp = await client.post(upstream, json=body, headers=headers, stream=True)
                break
            except httpx.ConnectError:
                if attempt == 0:
                    await asyncio.sleep(1)  # Brief pause for Render wake-up
                    continue
                raise

        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(resp.status_code, content={"error":f"Upstream {resp.status_code}","details":err.decode()[:200] if err else ""})

        # === RAW BYTE STREAMING (most reliable) ===
        async def stream():
            try:
                async for chunk in resp.aiter_bytes(chunk_size=256):
                    if chunk:
                        # Pass through exactly as received
                        yield chunk.decode('utf-8', errors='replace')
            except (httpx.ReadError, httpx.ConnectError, httpx.ReadTimeout, ConnectionResetError) as e:
                # Graceful finish on connection drop
                print(f"[Stream end] {type(e).__name__}")
                yield '\n {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n'
                yield ' [DONE]\n\n'
            except Exception as e:
                print(f"[Stream err] {e}")
            finally:
                await resp.aclose()
                await client.aclose()

        return StreamingResponse(stream(), media_type="text/event-stream")

    except httpx.ConnectError:
        return JSONResponse(502, content={"error":"Cannot connect to upstream (Render may be sleeping)","hint":"Wait 10s and retry"})
    except httpx.ReadTimeout:
        return JSONResponse(504, content={"error":"Upstream timeout","hint":"Try a smaller model or shorter response"})
    except Exception as e:
        print(f"[Proxy err] {type(e).__name__}: {e}")
        return JSONResponse(500, content={"error":"Internal error","details":str(e)[:100]})


# ==========================================
# 6. FALLBACK ENDPOINT
# ==========================================
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def fallback(request: Request):
    upstream = os.getenv("UPSTREAM_URL", "https://openrouter.ai/api/v1/chat/completions")
    try: body = await request.json()
    except: raise HTTPException(400, detail="Invalid JSON")
    body.setdefault("stream", True)
    headers = {"Content-Type":"application/json"}
    auth = request.headers.get("Authorization")
    if auth: headers["Authorization"] = auth
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    try:
        resp = await client.post(upstream, json=body, headers=headers, stream=True)
        if resp.status_code != 200:
            err = await resp.aread()
            return JSONResponse(resp.status_code, content={"error":f"Upstream {resp.status_code}"})
        async def stream():
            async for chunk in resp.aiter_bytes(256):
                if chunk: yield chunk.decode('utf-8', errors='replace')
            await client.aclose()
        return StreamingResponse(stream(), media_type="text/event-stream")
    except Exception as e:
        return JSONResponse(502, content={"error":str(e)[:150]})
    finally:
        await client.aclose()
