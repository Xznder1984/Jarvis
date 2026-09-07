import asyncio
import json
import base64
import sys
import subprocess
import tempfile
import os
import wave

sys.path.insert(0, '.')

import websockets


async def make_pcm(text: str) -> bytes:
    import edge_tts

    comm = edge_tts.Communicate(text, "en-GB-RyanNeural", rate="+0%", pitch="-8Hz")
    mp3 = bytearray()
    async for c in comm.stream():
        if c["type"] == "audio":
            mp3.extend(c["data"])
    tmp = tempfile.mkdtemp()
    src = os.path.join(tmp, "t.mp3")
    wav = os.path.join(tmp, "t.wav")
    open(src, "wb").write(bytes(mp3))
    subprocess.run(
        [
            "/usr/local/bin/ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            src,
            "-ar",
            "16000",
            "-ac",
            "1",
            "-sample_fmt",
            "s16",
            wav,
        ],
        check=True,
    )
    with wave.open(wav, "rb") as w:
        return w.readframes(w.getnframes())


async def main():
    tests = [
        ("wake", "jarvis", True),
        ("question", "what time is it", True),
        ("question", "tell me a joke", True),
        ("question", "what is 2 plus 2", True),
    ]
    async with websockets.connect("ws://127.0.0.1:8765/ws") as ws:
        await asyncio.wait_for(ws.recv(), timeout=5)
        for name, text, expect_say in tests:
            pcm = await make_pcm(text)
            print(f"Testing {name}: {text[:30]}...")
            await ws.send(json.dumps({"type": "wake_detected", "payload": {"method": "clap"}}))
            await ws.send(
                json.dumps(
                    {
                        "type": "audio_chunk",
                        "payload": {"data": base64.b64encode(pcm).decode(), "sample_rate": 16000},
                    }
                )
            )
            await ws.send(json.dumps({"type": "utterance_end", "payload": {}}))
            deadline = asyncio.get_event_loop().time() + 25
            got_say = False
            while asyncio.get_event_loop().time() < deadline:
                try:
                    m = json.loads(await asyncio.wait_for(ws.recv(), timeout=2.0))
                except asyncio.TimeoutError:
                    continue
                if m["type"] == "say":
                    p = m.get("payload", {})
                    print(f"  -> SAY ({p.get('provider')}): {repr(p.get('text', '')[:80])}")
                    got_say = True
                    break
            if not got_say:
                print(f"  -> NO SAY (timeout)")

    print("All tests completed")


if __name__ == "__main__":
    asyncio.run(main())