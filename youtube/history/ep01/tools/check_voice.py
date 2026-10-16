"""Check every chapter voice against its script with Gemini; list chapters to remake.

    python check_voice.py script.json voice_dir
Prints one line per chapter: OK, or BAD and what is wrong (English instructions read
aloud, extra or missing sentences, glitches). Exit code 1 if any chapter is BAD.
"""
import base64, json, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

MODELS = ("gemini-3.5-flash", "gemini-3-flash-preview", "gemini-flash-latest", "gemini-2.5-flash")
PROMPT = """You are checking a Hindi voiceover against its script.
SCRIPT (what should be spoken, nothing else):
{script}

Listen to the audio and answer in JSON only:
{{"extra_speech": "<any speech NOT in the script, especially English sentences such as instructions about how to speak; empty if none>",
  "missing": "<script sentences that were skipped; empty if none>",
  "glitches": "<clicks, cut-off words, garbled or robotic parts, with mm:ss; empty if none>",
  "ok": true or false}}
Single English loanwords that are inside the script (like मीटर, यूनेस्को) are fine."""


def ask(mp3, script):
    b = base64.b64encode(Path(mp3).read_bytes()).decode()
    body = {"contents": [{"parts": [{"inlineData": {"mimeType": "audio/mpeg", "data": b}},
                                    {"text": PROMPT.format(script=script)}]}],
            "generationConfig": {"responseMimeType": "application/json"}}
    for attempt in range(5):
        for m in MODELS:
            try:
                req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent",
                                             json.dumps(body).encode(), {"Content-Type": "application/json"})
                d = json.load(urllib.request.urlopen(req, timeout=300))
                return json.loads(d["candidates"][0]["content"]["parts"][0]["text"])
            except urllib.error.HTTPError as e:
                if e.code not in (429, 500, 503, 404):
                    raise
            except (json.JSONDecodeError, KeyError):
                pass
        time.sleep(45)
    return {"ok": None, "glitches": "checker unavailable"}


def main():
    sc = json.load(open(sys.argv[1], encoding="utf-8")); vdir = Path(sys.argv[2])
    only = set(sys.argv[3:])
    bad = []
    with tempfile.TemporaryDirectory() as td:
        for ch in sc["chapters"]:
            if only and ch["id"] not in only:
                continue
            wav = vdir / f"{ch['id']}.wav"
            if not wav.exists():
                print(ch["id"], "MISSING"); bad.append(ch["id"]); continue
            mp3 = Path(td) / f"{ch['id']}.mp3"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-b:a", "32k", str(mp3)], check=True)
            r = ask(mp3, "\n".join(s["text"] for s in ch["shots"]))
            ok = r.get("ok") is True and not r.get("extra_speech")
            print(ch["id"], "OK" if ok else "BAD", "" if ok else json.dumps(r, ensure_ascii=False), flush=True)
            if not ok:
                bad.append(ch["id"])
            time.sleep(8)
    print("REMAKE:", " ".join(bad) if bad else "none")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
