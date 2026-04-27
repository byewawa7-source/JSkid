#!/usr/bin/env python3
"""
JSkid Proxy v2 — Fly.io Optimized
Beautiful, robust, async-first LLM proxy with path-based routing.
"""
import os, re, json, time, asyncio, hashlib
from typing import Optional, List, Dict, Any
from urllib.parse import unquote, urlparse
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import httpx
import structlog
from fastapi import FastAPI, Request, HTTPException, Path, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator
from aiocache import cached, Cache

# Import beautiful UI
from config.themes import UIBuilder, THEMES

# ==========================================
# 1. CONFIGURATION
# ==========================================
@dataclass
class Config:
    """Application configuration with defaults."""
    presets: Dict[str, str] = field(default_factory=lambda: {
        "openrouter": "https://openrouter.ai/api/v1/chat/completions",
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "groq": "https://api.groq.com/openai/v1/chat/completions",
        "together": "https://api.together.xyz/v1/chat/completions",
        "deepseek": "https://api.deepseek.com/v1/chat/completions",
    })
    default_timeout: float = 120.0
    max_retries: int = 2
    cache_ttl: int = 300  # seconds
    max_memory_items: int = 100
    default_theme: str = "minimal"
    default_width: int = 64
    
    def resolve_upstream(self, prefix: str) -> Optional[str]:
        """Resolve upstream URL from path prefix or encoded URL."""
        if prefix in self.presets:
            return self.presets[prefix]
        try:
            decoded = unquote(prefix)
            parsed = urlparse(decoded)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                endpoint = "/chat/completions" if "messages" not in decoded else "/messages"
                return decoded.rstrip("/") + endpoint
        except Exception:
            pass
        return None

CONFIG = Config()

# ==========================================
# 2. STRUCTURED LOGGING
# ==========================================
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)
logger = structlog.get_logger("jskid")

# ==========================================
# 3. CORE ENGINE (Memory/Tags/State)
# ==========================================
class CoreState:
    """Lightweight state manager with memory limits."""
    __slots__ = ("memory", "vars", "tools", "_hash")
    
    def __init__(self):
        self.memory: List[str] = []
        self.vars: Dict[str, str] = {}
        self.tools: List[Dict] = []
        self._hash: Optional[str] = None
    
    def parse(self, messages: List[Dict]) -> "CoreState":
        """Extract tags from conversation history."""
        self.memory.clear()
        self.vars.clear()
        self.tools.clear()
        
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): continue
            
            tags = re.findall(
                r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|TOOL):\s*(.+?)\]\s*-->',
                content, re.DOTALL
            )
            for tag, val in tags:
                val = val.strip()
                if tag == "MEM_ADD" and val and len(self.memory) < CONFIG.max_memory_items:
                    if val not in self.memory: self.memory.append(val)
                elif tag == "MEM_DEL" and val in self.memory:
                    self.memory.remove(val)
                elif tag == "SET_VAR":
                    m = re.match(r'([^=]+)=\s*(.+)', val)
                    if m: self.vars[m.group(1).strip()] = m.group(2).strip().strip('"\'')
                elif tag == "TOOL":
                    try: self.tools.append(json.loads(val))
                    except: pass
        
        self._hash = self._compute_hash()
        return self
    
    def _compute_hash(self) -> str:
        """Compute state hash for caching."""
        data = f"{sorted(self.memory)}|{sorted(self.vars.items())}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def sanitize(self, messages: List[Dict]) -> List[Dict]:
        """Remove internal tags and skip command messages."""
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
    
    def inject_state(self, messages: List[Dict]) -> List[Dict]:
        """Add collected state as hidden context."""
        if not self.memory and not self.vars:
            return messages
        
        parts = ["\n<jskid_state>"]
        if self.memory: parts.append(f"mem:{';'.join(self.memory)}")
        if self.vars: parts.append(f"vars:{';'.join(f'{k}={v}' for k,v in self.vars.items())}")
        parts.append("</jskid_state>\n")
        
        state = "".join(parts)
        for msg in messages:
            if msg["role"] == "system":
                msg["content"] = msg.get("content", "") + state
                return messages
        messages.insert(0, {"role": "system", "content": state.strip()})
        return messages

# ==========================================
# 4. CIRCUIT BREAKER (Resilience)
# ==========================================
class CircuitBreaker:
    """Simple circuit breaker for upstream resilience."""
    
    def __init__(self, failure_threshold: int = 3, recovery_timeout: float = 30.0):
        self.failures = 0
        self.threshold = failure_threshold
        self.timeout = recovery_timeout
        self.last_failure: Optional[float] = None
        self.state = "closed"  # closed, open, half-open
    
    def record_success(self):
        self.failures = 0
        self.state = "closed"
    
    def record_failure(self):
        self.failures += 1
        self.last_failure = time.time()
        if self.failures >= self.threshold:
            self.state = "open"
            logger.warning("circuit opened", failures=self.failures)
    
    async def allow_request(self) -> bool:
        if self.state == "closed":
            return True
        if self.state == "open":
            if time.time() - self.last_failure > self.timeout:
                self.state = "half-open"
                logger.info("circuit half-open, testing")
                return True
            return False
        return True  # half-open: allow test request

# Global circuit breakers per upstream
_circuits: Dict[str, CircuitBreaker] = {}

def get_circuit(upstream: str) -> CircuitBreaker:
    if upstream not in _circuits:
        _circuits[upstream] = CircuitBreaker()
    return _circuits[upstream]

# ==========================================
# 5. CACHING (Optional)
# ==========================================
@cached(
    ttl=CONFIG.cache_ttl,
    cache=Cache.MEMORY,
    key_builder=lambda fn, prefix, body, **kw: f"{prefix}:{hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]}"
)
async def cached_completion(prefix: str, body: Dict) -> Optional[Dict]:
    """Cache non-streaming responses (optional optimization)."""
    return None  # Disable for now; enable by returning actual cached response

# ==========================================
# 6. FASTAPI LIFESPAN
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("jskid.v2.starting", presets=list(CONFIG.presets.keys()))
    yield
    logger.info("jskid.v2.stopped")

app = FastAPI(title="JSkid Proxy v2", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-request-id"],
)

# ==========================================
# 7. ENDPOINTS
# ==========================================
@app.get("/")
async def root():
    return {
        "service": "jskid-proxy",
        "version": "2.0.0",
        "status": "healthy",
        "presets": list(CONFIG.presets.keys()),
        "usage": "POST https://your-app.fly.dev/{preset}/v1/chat/completions",
        "docs": "https://github.com/you/jskid-proxy-v2"
    }

@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": time.time()}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [{"id": "jskid-v2", "object": "model", "owned_by": "jskid", "created": int(time.time())}]
    }

@app.get("/metrics")
async def metrics():
    """Simple metrics endpoint."""
    return {
        "circuits": {k: v.state for k, v in _circuits.items()},
        "presets": len(CONFIG.presets),
        "cache_ttl": CONFIG.cache_ttl,
    }

# ==========================================
# 8. BEAUTIFUL COMMAND HANDLERS
# ==========================================
def handle_local_command(content: str, core: CoreState, theme_name: str) -> Optional[JSONResponse]:
    """Handle /commands locally without upstream call."""
    ui = UIBuilder(theme_name)
    
    if content.startswith("/status"):
        return JSONResponse({
            "choices": [{"message": {"role": "assistant", "content": ui.status(
                "configured", len(core.memory), len(core.vars), theme_name
            )}}],
            "finish_reason": "stop"
        })
    
    if content.startswith("/reset"):
        core.memory.clear()
        core.vars.clear()
        return JSONResponse({
            "choices": [{"message": {"role": "assistant", "content": "✓ Memory cleared"}}],
            "finish_reason": "stop"
        })
    
    if content.startswith("/help") or content.startswith("/commands"):
        return JSONResponse({
            "choices": [{"message": {"role": "assistant", "content": ui.command_help()}}],
            "finish_reason": "stop"
        })
    
    theme_match = re.match(r'/theme\s+(\w+)', content)
    if theme_match:
        new_theme = theme_match.group(1).lower()
        if new_theme in THEMES:
            return JSONResponse({
                "choices": [{"message": {"role": "assistant", "content": 
                    f"✓ Theme changed to **{new_theme}**\n\n{UIBuilder(new_theme).status('active', len(core.memory), len(core.vars), new_theme)}"
                }}],
                "finish_reason": "stop"
            })
    
    return None

# ==========================================
# 9. OPTIMIZED STREAMING PROXY
# ==========================================
@app.post("/{prefix}/v1/chat/completions")
@app.post("/{prefix}/chat/completions")
async def proxy(
    request: Request,
    prefix: str = Path(..., description="Upstream preset or URL"),
    background_tasks: BackgroundTasks = None
):
    request_id = request.headers.get("x-request-id", f"req-{int(time.time()*1000)}")
    logger = structlog.get_logger("jskid").bind(request_id=request_id, prefix=prefix)
    
    # Resolve upstream
    upstream = CONFIG.resolve_upstream(prefix)
    if not upstream:
        raise HTTPException(400, detail=f"Unknown preset: {prefix}. Use: {list(CONFIG.presets.keys())}")
    
    # Parse request
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        logger.warning("invalid.json", error=str(e))
        raise HTTPException(400, detail="Invalid JSON")
    
    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(400, detail="No messages provided")
    
    # Initialize core
    core = CoreState().parse(messages)
    
    # Handle local commands
    last_content = messages[-1].get("content", "") if messages else ""
    cmd_response = handle_local_command(last_content, core, CONFIG.default_theme)
    if cmd_response:
        return cmd_response
    
    # Prepare payload
    clean_msgs = core.sanitize(messages)
    clean_msgs = core.inject_state(clean_msgs)
    body["messages"] = clean_msgs
    if core.tools:
        body["tools"] = core.tools
    body.setdefault("stream", True)
    
    # Headers
    headers = {"Content-Type": "application/json", "x-request-id": request_id}
    auth = request.headers.get("Authorization")
    if auth: headers["Authorization"] = auth
    for h in ["x-api-key", "http-referer", "x-title", "user-agent"]:
        if request.headers.get(h): headers[h] = request.headers[h]
    
    # Circuit breaker check
    circuit = get_circuit(upstream)
    if not await circuit.allow_request():
        logger.warning("circuit.open", upstream=upstream)
        return JSONResponse(503, content={
            "error": "Service temporarily unavailable",
            "hint": "Upstream circuit is open. Retry in 30s."
        })
    
    # HTTP client with connection pooling
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(CONFIG.default_timeout, connect=15.0, read=CONFIG.default_timeout, write=30.0),
        limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        http2=True,  # Enable HTTP/2 for better multiplexing
    ) as client:
        try:
            # Retry logic with exponential backoff
            last_error = None
            for attempt in range(CONFIG.max_retries + 1):
                try:
                    resp = await client.post(upstream, json=body, headers=headers, stream=True)
                    break
                except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                    last_error = e
                    if attempt < CONFIG.max_retries:
                        wait = min(2 ** attempt, 5)  # Cap at 5s
                        logger.info("retry.connect", attempt=attempt+1, wait=wait)
                        await asyncio.sleep(wait)
                        continue
                    raise
            
            if resp.status_code >= 400:
                err = await resp.aread()
                circuit.record_failure()
                logger.error("upstream.error", status=resp.status_code, upstream=upstream)
                return JSONResponse(resp.status_code, content={
                    "error": f"Upstream {resp.status_code}",
                    "details": err.decode()[:200] if err else ""
                })
            
            circuit.record_success()
            
            # === OPTIMIZED STREAMING ===
            async def stream_proxy():
                ui = UIBuilder(CONFIG.default_theme)
                buffer, chunk_count = "", 0
                
                try:
                    async for chunk in resp.aiter_bytes(chunk_size=512):
                        if not chunk: continue
                        
                        text = chunk.decode('utf-8', errors='replace')
                        buffer += text
                        chunk_count += 1
                        
                        # Yield complete SSE lines
                        while '\n\n' in buffer:
                            line, buffer = buffer.split('\n\n', 1)
                            if line.strip():
                                yield f"{line}\n\n"
                    
                    # Flush remaining buffer
                    if buffer.strip():
                        yield f"{buffer}\n\n"
                    
                    # Optional beautiful footer for short responses
                    if chunk_count < 20:
                        footer = f"\n\n{ui.status(upstream, len(core.memory), len(core.vars), CONFIG.default_theme)}"
                        yield f' {{"choices":[{{"delta":{{"content":{json.dumps(footer)}}}},"finish_reason":"stop"}}]}}\n\n'
                    
                    yield " [DONE]\n\n"
                    
                except (httpx.ReadError, httpx.ReadTimeout, ConnectionResetError, BrokenPipeError) as e:
                    logger.warning("stream.interrupted", error=type(e).__name__)
                    # Graceful finish
                    yield ' {"choices":[{"delta":{"content":""},"finish_reason":"stop"}]}\n\n'
                    yield " [DONE]\n\n"
                    
                except asyncio.CancelledError:
                    logger.info("stream.cancelled")
                    
                except Exception as e:
                    logger.error("stream.error", error=str(e))
                    yield f' {{"error":"Stream error"}}\n\n'
                
                finally:
                    await resp.aclose()
            
            return StreamingResponse(
                stream_proxy(),
                media_type="text/event-stream",
                headers={"x-request-id": request_id}
            )
            
        except httpx.ConnectError:
            circuit.record_failure()
            logger.error("connect.failed", upstream=upstream)
            return JSONResponse(502, content={
                "error": "Cannot connect to upstream",
                "hint": "Service may be starting. Retry in 10s."
            })
        except httpx.TimeoutException:
            circuit.record_failure()
            logger.error("timeout", upstream=upstream)
            return JSONResponse(504, content={
                "error": "Upstream timeout",
                "hint": "Try a smaller model or shorter prompt"
            })
        except Exception as e:
            logger.exception("proxy.error", error=type(e).__name__)
            return JSONResponse(500, content={
                "error": "Internal error",
                "details": str(e)[:100]
            })

# ==========================================
# 10. FALLBACK ENDPOINT
# ==========================================
@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def fallback_proxy(request: Request):
    """Standard endpoint using env-configured upstream."""
    upstream = os.getenv("UPSTREAM_URL", CONFIG.presets["openrouter"])
    
    try:
        body = await request.json()
    except:
        raise HTTPException(400, detail="Invalid JSON")
    
    body.setdefault("stream", True)
    headers = {"Content-Type": "application/json"}
    auth = request.headers.get("Authorization")
    if auth: headers["Authorization"] = auth
    
    async with httpx.AsyncClient(timeout=httpx.Timeout(CONFIG.default_timeout)) as client:
        try:
            resp = await client.post(upstream, json=body, headers=headers, stream=True)
            if resp.status_code != 200:
                return JSONResponse(resp.status_code, content={"error": f"Upstream {resp.status_code}"})
            
            async def stream():
                async for chunk in resp.aiter_bytes(512):
                    if chunk: yield chunk.decode('utf-8', errors='replace')
                await resp.aclose()
            
            return StreamingResponse(stream(), media_type="text/event-stream")
        except Exception as e:
            return JSONResponse(502, content={"error": str(e)[:150]})
