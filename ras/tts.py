import asyncio
import time

import edge_tts

from .config import AUDIO_DIR


async def _synth(text, voice, out_path):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(str(out_path))


def generate(text, voice="en-IN-NeerjaNeural"):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    out_path = AUDIO_DIR / f"ras_{int(time.time() * 1000)}.mp3"
    asyncio.run(_synth(text, voice, out_path))
    return out_path
