import io
import os
import re
from threading import Thread
import discord
from discord.ext import commands
from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot aktif!"

def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web, daemon=True)
    t.start()

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

def decode_string_char(code: str) -> str:
    pattern = re.compile(r"string\.char\s*\(\s*([0-9a-fA-FxX,\s]+)\s*\)")

    def replacer(match: re.Match) -> str:
        chars = []
        try:
            for item in match.group(1).split(","):
                item = item.strip()
                if not item:
                    continue
                val = int(item, 0)
                if 32 <= val <= 126:
                    chars.append(chr(val))
                elif val in (9, 10, 13):
                    chars.append({9: "\\t", 10: "\\n", 13: "\\r"}[val])
                else:
                    return match.group(0)
        except ValueError:
            return match.group(0)
        decoded = "".join(chars).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{decoded}"'

    return pattern.sub(replacer, code)

def decode_escape_sequences(code: str) -> str:
    string_pattern = re.compile(r'(["\'])(?:\\.|(?!\1).)*\1')

    def unescape_literal(match: re.Match) -> str:
        literal = match.group(0)
        quote, inner = literal[0], literal[1:-1]
        inner = re.sub(
            r"\\x([0-9a-fA-F]{2})",
            lambda m: chr(int(m.group(1), 16))
            if 32 <= int(m.group(1), 16) <= 126 and chr(int(m.group(1), 16)) not in (quote, "\\")
            else m.group(0),
            inner,
        )
        inner = re.sub(
            r"\\(\d{1,3})",
            lambda m: chr(int(m.group(1), 10))
            if 32 <= int(m.group(1), 10) <= 126 and chr(int(m.group(1), 10)) not in (quote, "\\")
            else m.group(0),
            inner,
        )
        return f"{quote}{inner}{quote}"

    return string_pattern.sub(unescape_literal, code)

def beautify_lua(code: str) -> str:
    strings = []

    def mask_string(match: re.Match) -> str:
        strings.append(match.group(0))
        return f"__LUA_STR_{len(strings) - 1}__"

    masked = re.sub(
        r'(\[\[[\s\S]*?\]\]|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')',
        mask_string,
        code,
    )
    masked = re.sub(r";+", "\n", masked)
    masked = re.sub(r"\b(then|do)\b", r"\1\n", masked)
    masked = re.sub(r"\b(end|else|elseif|until)\b", r"\n\1", masked)
    masked = re.sub(r"\b(local\s+function|function)\b", r"\n\1", masked)

    lines = [line.strip() for line in masked.splitlines() if line.strip()]
    formatted, indent = [], 0
    for line in lines:
        if re.match(r"^(end|else|elseif|until|\})\b", line):
            indent = max(0, indent - 1)
        formatted.append(("    " * indent) + line)
        opens = len(re.findall(r"\b(function|then|do|repeat)\b", line)) + line.count("{")
        closes = len(re.findall(r"\b(end|until)\b", line)) + line.count("}")
        indent = indent + 1 if re.match(r"^(else|elseif)\b", line) else max(0, indent + opens - closes)

    result = "\n".join(formatted)
    for idx, original in enumerate(strings):
        result = result.replace(f"__LUA_STR_{idx}__", original)
    return result

def scan_indicators(code: str) -> list[str]:
    indicators = {
        "Discord Webhook": r"discord(?:app)?\.com/api/webhooks",
        "HTTP Request": r"\b(HttpGet|HttpPost|request|http_request)\b",
        "Dynamic Execution (loadstring)": r"\b(loadstring|load)\b",
        "Environment Manipulation": r"\b(getfenv|setfenv)\b",
        "System Command": r"\b(os\.execute|io\.popen)\b",
    }
    return [label for label, pat in indicators.items() if re.search(pat, code, re.IGNORECASE)]

@bot.event
async def on_ready():
    print(f"Bot aktif sebagai {bot.user}")

@bot.command(name="deobf")
async def deobfuscate(ctx: commands.Context, *, code_input: str = None):
    if ctx.message.attachments:
        att = ctx.message.attachments[0]
        if not att.filename.endswith((".lua", ".txt")):
            await ctx.reply("Unggah file `.lua` atau `.txt`.")
            return
        raw_code = (await att.read()).decode("utf-8", errors="replace")
    elif code_input:
        raw_code = re.sub(r"^```(?:lua)?\s*|\s*```$", "", code_input.strip())
    else:
        await ctx.reply("Kirim `!deobf` disertai file `.lua` atau blok kode.")
        return

    cleaned = beautify_lua(decode_escape_sequences(decode_string_char(raw_code)))
    flags = scan_indicators(cleaned)

    embed = discord.Embed(title="Hasil Deobfuscation Lua", color=discord.Color.blue())
    embed.add_field(
        name="Indikator Terdeteksi",
        value=", ".join(flags) if flags else "Aman (tidak ada pola mencurigakan)",
        inline=False,
    )
    output = discord.File(io.BytesIO(cleaned.encode("utf-8")), filename="deobfuscated.lua")
    await ctx.reply(embed=embed, file=output)

keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])
