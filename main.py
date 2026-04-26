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

# ==========================================
# 1. CONFIGURATION
# ==========================================
TARGET_API = os.getenv("UPSTREAM_URL", "https://api-inference.huggingface.co/models/meta-llama/Meta-Llama-3-70B-Instruct")
PROXY_KEY = os.getenv("PROXY_KEY", None)
UI_WIDTH = int(os.getenv("UI_WIDTH", "54"))

# ==========================================
# 2. TUI ENGINE
# ==========================================
class JSkidUIEngine:
    def __init__(self, width=UI_WIDTH):
        self.width = width
        self.chars = {
            "tl": "┏", "tr": "┓", "bl": "┗", "br": "┛",
            "h": "━", "v": "┃", "t_left": "┣", "t_right": "┫"
        }

    def _pad(self, text: str, align: str = "left") -> str:
        max_len = self.width - 4
        if len(text) > max_len:
            text = text[:max_len - 3] + "..."
        padding = max_len - len(text)
        if align == "center":
            left = padding // 2
            right = padding - left
            return " " * left + text + " " * right
        elif align == "right":
            return " " * padding + text
        return text.ljust(max_len)

    def _line(self, char: str, count: int) -> str:
        return char * count

    def header(self, title: str) -> str:
        title_str = f" {title} "
        total_len = len(title_str) + 2
        remaining = self.width - total_len
        left = remaining // 2
        right = remaining - left
        return f"{self.chars['tl']}{self._line(self.chars['h'], left)}{title_str}{self._line(self.chars['h'], right)}{self.chars['tr']}"

    def footer(self) -> str:
        return f"{self.chars['bl']}{self._line(self.chars['h'], self.width - 2)}{self.chars['br']}"

    def separator(self) -> str:
        return f"{self.chars['t_left']}{self._line(self.chars['h'], self.width - 2)}{self.chars['t_right']}"

    def row(self, text: str, align: str = "left") -> str:
        return f"{self.chars['v']} {self._pad(text, align)} {self.chars['v']}"

    def command_list(self, commands: list) -> str:
        lines = [self.separator()]
        for cmd in commands:
            lines.append(self.row(f"> {cmd}"))
        lines.append(self.footer())
        return "\n".join(lines)

    def render_dashboard(self, title: str, status: str, memory_count: int, 
                         chars: dict, commands: list = None, extra_info: dict = None) -> str:
        lines = ["```bash"]
        lines.append(self.header(title))
        lines.append(self.row(f"STATUS: {status}", "center"))
        lines.append(self.row(f"MEMORY: {memory_count} Active Facts"))
        chars_preview = ", ".join([f"{k}={v}" for k, v in chars.items()]) if chars else "None"
        lines.append(self.row(f"CHARS:  {chars_preview}"))
        if extra_info:
            lines.append(self.separator())
            for k, v in extra_info.items():
                lines.append(self.row(f"• {k}: {v}"))
        if commands:
            lines.append(self.command_list(commands))
        else:
            lines.append(self.footer())
        lines.append("```")
        return "\n".join(lines)

# ==========================================
# 3. EXTENSION MANAGER
# ==========================================
class ExtensionManager:
    def __init__(self):
        self.modules = {}
        self.loaded_scripts = []

    def execute_script(self, script_code: str, context: dict) -> dict:
        local_env = context.copy()
        try:
            exec(script_code, globals(), local_env)
            return local_env
        except Exception as e:
            print(f"[Extension] Runtime Error: {e}")
            return context

# ==========================================
# 4. CORE ENGINE
# ==========================================
class JSkidEngine:
    def __init__(self):
        self.ui = JSkidUIEngine()
        self.ext_manager = ExtensionManager()
        self.memory = []
        self.chars = {}
        self.tools = []

    def parse_state(self, messages):
        self.memory.clear()
        self.chars.clear()
        self.tools.clear()

        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str): continue
            tags = re.findall(r'<!--\s*\[(SET_VAR|MEM_ADD|MEM_DEL|EXT|TOOL):\s*(.*?)]\s*-->', content, re.DOTALL)
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

    def sanitize(self, messages):
        clean = []
        for msg in messages:
            content = msg.get("content", "")
            if not isinstance(content, str) or not content:
                clean.append(msg)
                continue
            content = re.sub(r'<!--.*?-->', '', content, flags=re.DOTALL)
            content = re.sub(r'```bash\n┏.*?┛\n```', '', content, flags=re.DOTALL)
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
# 5. FASTAPI APPLICATION WITH CORS
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    print(f"--- JSkid Proxy Started ---")
    print(f"Target API URL: {TARGET_API}")
    print(f"Proxy Key Set: {'Yes' if PROXY_KEY else 'No'}")
    print("---------------------------")
    yield

app = FastAPI(title="JSkid Proxy", lifespan=lifespan)

# --- ENABLE CORS ---
# This allows JanitorAI (and any other site) to make requests to your Space.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (JanitorAI, browser tests, etc.)
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods (GET, POST, OPTIONS)
    allow_headers=["*"],  # Allows all headers
)

# --- Standard Endpoints ---
@app.get("/")
async def health_check():
    return {"status": "ok", "service": "JSkid Proxy", "target_api": TARGET_API}

@app.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "jskid-model", "object": "model", "owned_by": "jskid", "created": int(time.time())}
        ]
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/test")
async def test_endpoint():
    return {
        "status": "success",
        "message": "JSkid Proxy is running correctly with CORS enabled.",
        "endpoint": "/v1/chat/completions",
        "method": "POST",
        "note": "Use a POST client (JanitorAI, curl, Postman) to test chat."
    }

# --- Chat Completion Endpoint ---
async def intercept_upstream_stream(response: httpx.Response):
    buffer = ""
    in_bracket = False

    async for line in response.aiter_lines():
        if not line.startswith("data: "):
            continue
        data_str = line[6:]
        
        if data_str == "[DONE]":
            if buffer:
                yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
            yield "data: [DONE]\n\n"
            break

        try:
            data = json.loads(data_str)
            delta = data["choices"][0].get("delta", {})
            if "content" in delta:
                text = delta["content"]
                for char in text:
                    if char == '[':
                        in_bracket = True
                        buffer += char
                    elif char == ']' and in_bracket:
                        buffer += char
                        in_bracket = False
                        if re.match(r'^\[(SET_VAR|MEM_ADD|MEM_DEL|EXT|TOOL):.*?\]$', buffer):
                            yield f"data: {json.dumps({'choices':[{'delta': {'content': f'<!--{buffer}-->'}}]})}\n\n"
                        else:
                            yield f"data: {json.dumps({'choices':[{'delta': {'content': buffer}}]})}\n\n"
                        buffer = ""
                    elif in_bracket:
                        buffer += char
                        if len(buffer) > 1000:
                            yield f"data: {json.dumps({'choices': [{'delta': {'content': buffer}}]})}\n\n"
                            buffer = ""
                            in_bracket = False
                    else:
                        yield f"data: {json.dumps({'choices': [{'delta': {'content': char}}]})}\n\n"
        except json.JSONDecodeError:
            pass

@app.post("/v1/chat/completions")
async def chat_proxy(request: Request):
    # Auth
    if PROXY_KEY and request.headers.get("x-proxy-key") != PROXY_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = payload.get("messages", [])
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")

    engine = JSkidEngine()
    engine.parse_state(messages)

    last_msg = messages[-1].get("content", "")
    op_instruction = None
    oop_mode = False

    # Handle /OP and /OOP
    if last_msg.startswith("/OP ") or last_msg.startswith("/OOP "):
        if last_msg.startswith("/OOP "):
            oop_mode = True
            op_instruction = last_msg[5:].strip()
        else:
            op_instruction = last_msg[4:].strip()
        
        if op_instruction:
            engine.memory.append(f"OP_INSTRUCTION: {op_instruction}")
            messages[-1]["content"] = ""

    if op_instruction:
        instruction_text = f"\n<system_instruction>\nIMPORTANT: OOC Command: \"{op_instruction}\". Follow strictly.\n</system_instruction>"
        injected = False
        for msg in messages:
            if msg["role"] == "system":
                msg["content"] += instruction_text
                injected = True
                break
        if not injected:
            messages.insert(0, {"role": "system", "content": instruction_text})

        if oop_mode:
            messages.append({
                "role": "system",
                "content": "<!--[MEM_ADD: OOP Success]-->\n[System: Instruction received. Resuming.]"
            })

    clean_msgs = engine.sanitize(messages)
    clean_msgs = engine.inject_world_state(clean_msgs)
    
    payload["messages"] = clean_msgs
    if engine.tools:
        payload["tools"] = engine.tools

    if "stream" not in payload:
        payload["stream"] = True

    headers = {
        "Authorization": request.headers.get("Authorization", ""),
        "Content-Type": "application/json"
    }

    client = httpx.AsyncClient(timeout=120.0)
    try:
        req = client.build_request("POST", TARGET_API, json=payload, headers=headers)
        resp = await client.send(req, stream=True)
        
        if resp.status_code != 200:
            error_content = await resp.aread()
            return JSONResponse(
                status_code=resp.status_code,
                content={"error": f"Upstream API Error: {resp.status_code}", "details": error_content.decode()}
            )

        return StreamingResponse(
            intercept_upstream_stream(resp), 
            media_type="text/event-stream",
            background=client.aclose
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": "Internal Server Error", "details": str(e)}
        )
