"""Natural Hindi narration with Google Gemini TTS (same voices MoneyPrinterTurbo uses).

    GEMINI_API_KEY=... python gemini_voice.py ../script.json ../voice_gemini [--model gemini-2.5-pro-preview-tts]

Makes one file per chapter (voice_gemini/c01.wav ...). Chapters with a second speaker
use Gemini's two-speaker mode. make_episode.py spreads each chapter across its scenes.
"""
import argparse, base64, json, os, subprocess, sys, time, urllib.request, urllib.error, wave
from pathlib import Path

NAMES = {"n": "Gappu", "f": "Aurat", "m": "Mazdoor"}
VOICE = {"n": "Algenib", "f": "Sulafat", "m": "Puck"}
STYLE = ("Read this in natural, fluent Hindi with a proper Indian accent, like a warm, funny old village storyteller "
         "(dada-ji) telling a story to children. Slow, expressive pace, a smile in the voice, playful on the jokes, "
         "a short pause at '...' and after each sentence. Not robotic, not a newsreader.")
STYLE2 = {"f": "Aurat speaks like a confident, sharp young Indian woman.",
          "m": "Mazdoor speaks like an excited, simple labourer."}


def call(model, key, body, tries=6):
    # With a plain environment variable the key goes in the x-goog-api-key header; with a
    # network secret the session's proxy adds that header itself and key is empty.
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {"Content-Type": "application/json"}
    if key:
        headers["x-goog-api-key"] = key
    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.load(r)
            part = data["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
            return base64.b64decode(part)
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:400]
            if e.code in (429, 500, 503) and i < tries - 1:
                wait = 30 * (i + 1); print(f"  busy ({e.code}), waiting {wait}s"); time.sleep(wait); continue
            sys.exit(f"Gemini error {e.code}: {msg}")


def chapter_body(ch):
    speakers = []
    for s in ch["shots"]:
        sp = s.get("speaker", "n")
        if sp not in speakers:
            speakers.append(sp)
    if len(speakers) == 1:
        text = " ".join(s["text"] for s in ch["shots"])
        return {"contents": [{"parts": [{"text": f"{STYLE}\n\n{text}"}]}],
                "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE[speakers[0]]}}}}}
    lines, last = [], None
    for s in ch["shots"]:
        n = NAMES[s.get("speaker", "n")]
        if n == last:
            lines[-1] += " " + s["text"]
        else:
            lines.append(f"{n}: {s['text']}"); last = n
    extra = " ".join(STYLE2[sp] for sp in speakers if sp in STYLE2)
    prompt = f"{STYLE} Gappu is the storyteller. {extra}\n\n" + "\n".join(lines)
    return {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {"multiSpeakerVoiceConfig": {
                "speakerVoiceConfigs": [{"speaker": NAMES[sp], "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE[sp]}}}
                                        for sp in speakers[:2]]}}}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("script"); ap.add_argument("out")
    ap.add_argument("--model", default="gemini-3.8-flash-tts")  # free tier; pro TTS may need billing
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    key = os.environ.get("GEMINI_API_KEY", "")   # empty when a network secret supplies the header
    sc = json.load(open(a.script, encoding="utf-8")); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    for ch in sc["chapters"]:
        if a.only and ch["id"] not in a.only:
            continue
        dst = out / f"{ch['id']}.wav"
        if dst.exists() and not a.only:
            continue
        # one request per run of lines by the same speaker, joined with a short breath
        runs = []
        for s in ch["shots"]:
            sp = s.get("speaker", "n")
            if runs and runs[-1][0] == sp:
                runs[-1][1].append(s["text"])
            else:
                runs.append([sp, [s["text"]]])
        parts = []
        for k, (sp, texts) in enumerate(runs):
            style = STYLE if sp == "n" else STYLE2[sp] + " Natural fluent Hindi, Indian accent, expressive, not robotic."
            body = {"contents": [{"parts": [{"text": f"{style}\n\n{' '.join(texts)}"}]}],
                    "generationConfig": {"responseModalities": ["AUDIO"], "speechConfig": {
                        "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE[sp]}}}}}
            pcm = call(a.model, key, body)
            f = out / f"{ch['id']}_part{k}.wav"
            with wave.open(str(f), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
            parts.append(f)
            if k < len(runs) - 1:
                time.sleep(21)
        lst = out / f"{ch['id']}_list.txt"
        gap = out / "gap.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", "0.35", str(gap)], check=True)
        lst.write_text("".join(f"file '{p.resolve()}'\nfile '{gap.resolve()}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-af", "loudnorm=I=-16:TP=-1.5", "-ar", "48000", str(dst)], check=True)
        for p in parts: p.unlink()
        lst.unlink(); gap.unlink()
        print(ch["id"], "done", flush=True)
        time.sleep(21)   # stay under the free tier's ~3 requests a minute


if __name__ == "__main__":
    main()
