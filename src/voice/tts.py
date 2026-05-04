"""
edge-tts wrapper with aggressive pause reduction.
No API key required — uses Microsoft's free neural TTS (same voices as Edge browser).

Pause strategy for edge-tts (SSML break tags are not supported):
  - Sentence-ending periods/exclamations  →  commas  (~200ms vs ~750ms)
  - Em dashes, ellipses, semicolons       →  space or comma
  - Entire response sent as one synthesis request — eliminates inter-segment gaps
"""

import re
import asyncio
import os
import sys
import subprocess
import threading
import ctypes


def clean_text(text: str) -> str:
    """
    Strip formatting and replace heavy-pause punctuation with lighter alternatives.
    edge-tts doesn't support SSML <break> tags — punctuation type is our only
    lever for pause length. Comma ≈ 200ms, period ≈ 750ms in neural TTS.
    """
    # code blocks → gone (don't say the code)
    text = re.sub(r'```[\s\S]*?```', '', text)

    # markdown
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*',     r'\1', text)
    text = re.sub(r'`([^`]+)`',     r'\1', text)
    text = re.sub(r'#{1,6}\s',      '',    text)
    text = re.sub(r'\[.*?\]\(.*?\)', '',   text)
    text = re.sub(r'https?://\S+',  '',    text)

    # long-pause punctuation → short alternatives
    text = re.sub(r'[—\-]{2,}|–',   ' ',  text)   # em/en dash → space
    text = re.sub(r'\.{2,}|…',      ' ',  text)   # ellipsis → space

    # sentence-ending . and ! → comma  (shorter pause, same breath rhythm)
    # only when followed by whitespace so we don't mangle decimals like 3.14
    text = re.sub(r'[.!](\s)',       r',\1', text)

    # semicolons and mid-sentence colons → comma
    text = re.sub(r';',              ',', text)
    text = re.sub(r':(?!\n)',        ',', text)

    # parenthetical asides break speech rhythm
    text = re.sub(r'\(.*?\)',        '',  text)

    # list markers
    text = re.sub(r'^\s*[-•*]\s+',  '',  text, flags=re.MULTILINE)
    text = re.sub(r'^\s*\d+\.\s+',  '',  text, flags=re.MULTILINE)

    # collapse whitespace
    text = re.sub(r'\n+',    ' ', text)
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()


def speak(text: str, voice: str = "en-US-AndrewNeural", rate: str = "+25%") -> None:
    """
    Synthesize and play text. No API key required.
    Sends the full response as one request to avoid inter-segment gaps.
    """
    cleaned = clean_text(text)
    if not cleaned:
        return
    if len(cleaned) > 1500:
        cleaned = cleaned[:1500]

    try:
        import edge_tts
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "edge-tts"],
            capture_output=True
        )
        try:
            import edge_tts
        except Exception:
            return

    try:
        winmm = ctypes.windll.winmm
    except Exception:
        winmm = None

    async def _synthesize():
        data = b""
        async for chunk in edge_tts.Communicate(cleaned, voice, rate=rate).stream():
            if chunk["type"] == "audio":
                data += chunk["data"]
        return data

    loop = asyncio.new_event_loop()
    try:
        data = loop.run_until_complete(_synthesize())
    finally:
        loop.close()

    if not data:
        return

    cli_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    tmp = os.path.join(cli_dir, "temp_tts.mp3")
    with open(tmp, "wb") as f:
        f.write(data)

    if winmm:
        winmm.mciSendStringW(f'open "{tmp}" type mpegvideo alias div_tts', None, 0, None)
        winmm.mciSendStringW('play div_tts wait', None, 0, None)
        winmm.mciSendStringW('close div_tts', None, 0, None)


def speak_stream(text: str, voice: str = "en-US-AndrewNeural", rate: str = "+25%") -> None:
    """
    For long responses — speak sentence by sentence so audio starts
    immediately rather than waiting for the full block to synthesize.
    """
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    for sentence in (s.strip() for s in sentences if s.strip()):
        speak(sentence, voice=voice, rate=rate)
