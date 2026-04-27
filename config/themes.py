"""Beautiful terminal UI themes for JSkid Proxy v2."""
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class Theme:
    name: str
    border: Dict[str, str]
    colors: Dict[str, str]  # ANSI codes (for terminals that support them)
    header_style: str
    width: int = 64

THEMES: Dict[str, Theme] = {
    "cyberpunk": Theme(
        name="Cyberpunk",
        border={"tl":"╔","tr":"╗","bl":"╚","br":"╝","h":"═","v":"║","x":"╳"},
        colors={"primary":"\033[95m","secondary":"\033[96m","accent":"\033[93m","reset":"\033[0m"},
        header_style="glow",
        width=64
    ),
    "minimal": Theme(
        name="Minimal",
        border={"tl":"┌","tr":"┐","bl":"└","br":"┘","h":"─","v":"│","x":"·"},
        colors={"primary":"","secondary":"","accent":"","reset":""},
        header_style="clean",
        width=64
    ),
    "retro": Theme(
        name="Retro CRT",
        border={"tl":"▛","tr":"▜","bl":"▙","br":"▟","h":"▀","v":"▌","x":"×"},
        colors={"primary":"\033[32m","secondary":"\033[32m","accent":"\033[1;32m","reset":"\033[0m"},
        header_style="blink",
        width=64
    ),
    "elegant": Theme(
        name="Elegant",
        border={"tl":"╭","tr":"╮","bl":"╰","tr":"╯","h":"─","v":"│","x":"•"},
        colors={"primary":"\033[38;5;250m","secondary":"\033[38;5;245m","accent":"\033[38;5;117m","reset":"\033[0m"},
        header_style="italic",
        width=72
    ),
    "brutalist": Theme(
        name="Brutalist",
        border={"tl":"█","tr":"█","bl":"█","br":"█","h":"▄","v":"█","x":"✖"},
        colors={"primary":"\033[41;97m","secondary":"\033[40;97m","accent":"\033[43;30m","reset":"\033[0m"},
        header_style="bold",
        width=64
    ),
}

class UIBuilder:
    """Chat-compatible UI renderer with theme support."""
    
    def __init__(self, theme_name: str = "minimal"):
        self.theme = THEMES.get(theme_name, THEMES["minimal"])
        # Strip ANSI for chat compatibility by default
        self.use_ansi = False
    
    def _clean(self, text: str) -> str:
        """Remove ANSI codes for chat-safe output."""
        if not self.use_ansi:
            import re
            return re.sub(r'\x1b\[[0-9;]*m', '', text)
        return text
    
    def _visual_len(self, text: str) -> int:
        """Get visible character count."""
        import re
        return len(re.sub(r'\x1b\[[0-9;]*m|[^\x20-\x7E]', '', text))
    
    def _pad(self, text: str, width: int, align: str = "left") -> str:
        """Pad text to exact visual width."""
        visible = self._visual_len(text)
        padding = max(0, width - visible)
        if align == "center":
            l, r = padding // 2, padding - (padding // 2)
            return " " * l + text + " " * r
        elif align == "right":
            return " " * padding + text
        return text + " " * padding
    
    def _wrap(self, text: str, max_w: int) -> List[str]:
        """Word-wrap text."""
        if not text: return [""]
        words, lines, cur = text.split(), [], ""
        for w in words:
            test = f"{cur} {w}".strip()
            if self._visual_len(test) <= max_w:
                cur = test
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        return lines
    
    def box(self, title: str, lines: List[str], width: int = None) -> str:
        """Render a beautiful themed box."""
        w = width or self.theme.width
        c, iw = self.theme.border, w - 4
        
        # Header with styled title
        title_txt = f" {title} "
        if self.theme.header_style == "glow":
            title_txt = f"{self.theme.colors['accent']}{title_txt}{self.theme.colors['reset']}"
        elif self.theme.header_style == "bold":
            title_txt = f"\033[1m{title_txt}\033[0m"
        title_bar = self._pad(title_txt, iw, "center")
        
        header = f"{c['tl']}{c['h']}{title_bar}{c['h']}{c['tr']}"
        
        # Body with wrapped content
        body = []
        for line in lines:
            for wrapped in self._wrap(line, iw) if line else [""]:
                padded = self._pad(wrapped, iw, "left")
                body.append(f"{c['v']} {padded} {c['v']}")
        
        footer = f"{c['bl']}{c['h'] * (w - 2)}{c['br']}"
        
        return self._clean("\n".join([header] + body + [footer]))
    
    def status(self, upstream: str, memory: int, vars_count: int, theme: str) -> str:
        """Render compact status dashboard."""
        display = upstream.replace("https://","").replace("http://","").split("/")[0]
        if len(display) > 20: display = display[:17] + "…"
        return self.box("◈ JSKID v2", [
            f"Upstream : {display}",
            f"Theme    : {theme}",
            f"Memory   : {memory} facts",
            f"Vars     : {vars_count} active",
            f"Status   : ✓ Online"
        ])
    
    def command_help(self) -> str:
        """Render available commands."""
        return self.box("Commands", [
            "/status     — Show proxy status",
            "/reset      — Clear memory & variables", 
            "/theme <n>  — Change UI theme",
            "/width <n>  — Adjust box width (40-120)",
            "",
            "Tags in prompts:",
            "  <!-- [MEM_ADD: fact] -->",
            "  <!-- [SET_VAR: key=value] -->",
            "  <!-- [TOOL: {...}] -->"
        ])
