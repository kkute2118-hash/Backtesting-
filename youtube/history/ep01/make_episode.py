#!/usr/bin/env python3
"""Make a ready-to-upload cartoon history episode: free Hindi voices + your images -> MP4.

    pip install edge-tts pillow
    python make_episode.py script.json --images images --out episode01.mp4 --burn-subs

1. Voices: every scene's line is spoken with Microsoft's free neural Hindi voices
   (hi-IN-MadhurNeural for Gappu Kaka, hi-IN-SwaraNeural for women), saved in voice/s01.mp3...
   Already-made files are kept, so you can re-record or replace any single line.
   Use --no-tts to use only your own recordings (same file names), or record one file
   per chapter instead: voice/c01.mp3 ... c10.mp3.
2. Images: images/s01.png ... one 16:9 picture per scene (see image_prompts.txt).
3. Output: episode01.mp4 (1080p) + episode01.hi.srt (captions) + episode01.chapters.txt.
   Speech bubbles and cards are drawn on top; --burn-subs also burns Hindi subtitles.
   Fonts: Windows "Nirmala UI" (default); Mac --font "Kohinoor Devanagari";
   Linux --font "Noto Sans Devanagari".
Needs Python 3.9+ and ffmpeg on PATH.
"""
import argparse, json, re, shutil, subprocess, sys, tempfile
from pathlib import Path

W, H, FPS = 1920, 1080, 30
CARD_SECS = 4.0
WORDS_PER_SEC = 2.2


def run(cmd):
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode:
        sys.exit("ffmpeg failed:\n" + " ".join(map(str, cmd)) + "\n" + r.stderr[-2000:])
    return r.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", str(path)]).strip())


def find(folder, stem, exts):
    for e in exts:
        p = Path(folder) / f"{stem}.{e}"
        if p.exists():
            return p
    return None


def placeholder(path, label):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), (38, 34, 30))
    d = ImageDraw.Draw(img)
    for y in range(H):
        c = int(38 + 30 * y / H)
        d.line([(0, y), (W, y)], fill=(c, c - 4, c - 10))
    d.rectangle([60, 60, W - 60, H - 60], outline=(120, 100, 70), width=4)
    d.text((W // 2 - 60, H // 2 - 20), label, fill=(220, 200, 160))
    img.save(path)


def ts_ass(t):
    h, rem = divmod(t, 3600); m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def ts_srt(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def chunks(text, limit=58):
    """Split narration into subtitle lines at punctuation, about `limit` characters each."""
    parts = [p.strip() for p in re.split(r"(?<=[।?!,:])\s+", text) if p.strip()]
    out, cur = [], ""
    for p in parts:
        if cur and len(cur) + 1 + len(p) > limit:
            out.append(cur); cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    final = []
    for line in out:  # break very long lines on spaces
        while len(line) > limit + 20:
            cut = line.rfind(" ", 0, limit)
            cut = cut if cut > 0 else limit
            final.append(line[:cut]); line = line[cut:].strip()
        final.append(line)
    return final



def make_voices(sc, folder, only_missing=True):
    """Free natural Hindi voices (Microsoft Edge neural TTS) for every scene."""
    try:
        import asyncio, edge_tts
    except ImportError:
        sys.exit("Install the free voice tool first:  pip install edge-tts")
    Path(folder).mkdir(parents=True, exist_ok=True)

    async def one(s):
        out = Path(folder) / f"{s['id']}.mp3"
        if only_missing and out.exists() and out.stat().st_size > 0:
            return
        v = sc["voices"][s.get("speaker", "n")]
        for attempt in range(3):
            try:
                await edge_tts.Communicate(s["text"], v["edge"], rate=v.get("rate", "+0%"),
                                           pitch=v.get("pitch", "+0Hz")).save(str(out))
                return
            except Exception as e:
                if attempt == 2:
                    sys.exit(f"voice failed for {s['id']}: {e}")
                await asyncio.sleep(3)

    async def all_():
        shots = [s for c in sc["chapters"] for s in c["shots"]]
        for i, s in enumerate(shots, 1):
            await one(s)
            print(f"  voice {i}/{len(shots)}", end="\r")
        print()
    asyncio.run(all_())


def main():
    ap = argparse.ArgumentParser(description="Build a cartoon history episode with free Hindi voices.")
    ap.add_argument("script")
    ap.add_argument("--images", default="images")
    ap.add_argument("--voice", default="voice")
    ap.add_argument("--out", default="episode.mp4")
    ap.add_argument("--music")
    ap.add_argument("--music-volume", type=float, default=0.08)
    ap.add_argument("--font", default="Nirmala UI")
    ap.add_argument("--fontsdir")
    ap.add_argument("--burn-subs", action="store_true")
    ap.add_argument("--no-tts", action="store_true", help="use your own recordings in --voice instead of generating")
    ap.add_argument("--redo-voice", action="store_true", help="regenerate every voice file")
    ap.add_argument("--preview", action="store_true", help="allow missing voice/images (silent timing, placeholders)")
    a = ap.parse_args()

    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            sys.exit(f"{tool} not found on PATH")
    sc = json.load(open(a.script, encoding="utf-8"))
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True); stem = out.with_suffix("")
    tmp = Path(tempfile.mkdtemp(prefix="ep_"))
    if not a.no_tts and not a.preview:
        print("making voices (free Edge neural TTS)...")
        make_voices(sc, a.voice, only_missing=not a.redo_voice)

    # 1. each scene lasts as long as its own line plus a short breath
    shots, audio_parts, t, marks = [], [], 0.0, []
    for ch in sc["chapters"]:
        marks.append((t, ch["title"]))
        chvoice = find(a.voice, ch["id"], ("mp3", "wav", "m4a"))
        if chvoice and not find(a.voice, ch["shots"][0]["id"], ("mp3", "wav", "m4a")):
            # one recording for the whole chapter: share its length across scenes by text length
            part = tmp / f"{ch['id']}.wav"
            run(["ffmpeg", "-y", "-i", str(chvoice), "-af", "apad=pad_dur=0.9", "-ar", "48000", "-ac", "2", str(part)])
            audio_parts.append(part)
            cd, tc = duration(part), sum(len(x["text"]) for x in ch["shots"])
            for s in ch["shots"]:
                d = cd * len(s["text"]) / tc
                shots.append({**s, "start": t, "dur": d}); t += d
            continue
        for k, s in enumerate(ch["shots"]):
            gap = 0.9 if k == len(ch["shots"]) - 1 else 0.35
            voice = find(a.voice, s["id"], ("mp3", "wav", "m4a"))
            part = tmp / f"{s['id']}.wav"
            if voice:
                vd = duration(voice)
                run(["ffmpeg", "-y", "-i", str(voice), "-af", f"apad=pad_dur={gap}", "-ar", "48000", "-ac", "2", str(part)])
            elif a.preview:
                vd = len(s["text"].split()) / WORDS_PER_SEC
                run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{vd+gap:.3f}", str(part)])
            else:
                sys.exit(f"missing voice {s['id']} in {a.voice}/")
            d = duration(part)
            audio_parts.append(part)
            shots.append({**s, "start": t, "dur": d}); t += d
    total = t
    print(f"{len(shots)} scenes, {total/60:.1f} minutes")

    # 2. one gently moving clip per scene
    clips = []
    for i, s in enumerate(shots):
        img = find(a.images, s["id"], ("png", "jpg", "jpeg", "webp"))
        if not img:
            if not a.preview:
                sys.exit(f"missing image {s['id']} in {a.images}/")
            img = tmp / f"{s['id']}_ph.png"; placeholder(img, s["id"])
        frames = max(1, round(s["dur"] * FPS))
        z = (f"min(1+0.06*on/{frames},1.06)" if i % 2 == 0 else f"max(1.06-0.06*on/{frames},1.0)")
        vf = (f"scale={W*2}:{H*2}:force_original_aspect_ratio=increase,crop={W*2}:{H*2},"
              f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{H}:fps={FPS},format=yuv420p")
        clip = tmp / f"{s['id']}.mp4"
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(img), "-vf", vf, "-frames:v", str(frames),
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(clip)])
        clips.append(clip)
        print(f"  scene {i+1}/{len(shots)}", end="\r")
    print()

    # 3. captions, speech bubbles and cards
    srt, ev, n = [], [], 1
    for i, s in enumerate(shots):
        lines = chunks(s["text"]); tl = sum(len(l) for l in lines); st = s["start"]
        speak = s["dur"] - (0.9 if s is shots[-1] else 0.35)
        for l in lines:
            d = speak * len(l) / tl
            srt.append(f"{n}\n{ts_srt(st)} --> {ts_srt(st + d)}\n{l}\n"); n += 1
            if a.burn_subs:
                ev.append(f"Dialogue: 0,{ts_ass(st)},{ts_ass(st + d)},Sub,,0,0,0,,{l}")
            st += d
        if s.get("bubble"):
            style = "BubbleL" if i % 2 == 0 else "BubbleR"
            ev.append(f"Dialogue: 2,{ts_ass(s['start'] + 0.25)},{ts_ass(s['start'] + s['dur'] - 0.1)},{style},,0,0,0,,"
                      f"{{\\fad(150,150)\\fscx80\\fscy80\\t(0,180,\\fscx100\\fscy100)}}{s['bubble']}")
        if s.get("card"):
            ev.append(f"Dialogue: 1,{ts_ass(s['start'] + 0.3)},{ts_ass(s['start'] + min(CARD_SECS, s['dur']))},Card,,0,0,0,,"
                      f"{{\\fad(300,300)}}{s['card']}")
    Path(f"{stem}.hi.srt").write_text("\n".join(srt), encoding="utf-8")
    ass = tmp / "overlay.ass"
    ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{a.font},50,&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,1,0,0,0,100,100,0,0,3,10,0,2,200,200,50,1
Style: BubbleL,{a.font},64,&H00141414,&H00141414,&H00FFFFFF,&H00141414,1,0,0,0,100,100,0,0,3,22,0,7,170,170,110,1
Style: BubbleR,{a.font},64,&H00141414,&H00141414,&H00FFFFFF,&H00141414,1,0,0,0,100,100,0,0,3,22,0,9,170,170,110,1
Style: Card,{a.font},66,&H0080D8F5,&H00FFFFFF,&H00202020,&HA0000000,1,0,0,0,100,100,0,0,3,16,0,8,120,120,60,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""" + "\n".join(ev) + "\n", encoding="utf-8")
    Path(f"{stem}.chapters.txt").write_text(
        "\n".join(f"{int(t0//60)}:{int(t0%60):02d} {title}" for t0, title in marks) + "\n", encoding="utf-8")

    # 4. join, add music, burn overlay
    lst = tmp / "clips.txt"; lst.write_text("".join(f"file '{c.as_posix()}'\n" for c in clips))
    alst = tmp / "audio.txt"; alst.write_text("".join(f"file '{p.as_posix()}'\n" for p in audio_parts))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(tmp / "video.mp4")])
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(alst), "-c:a", "pcm_s16le", str(tmp / "voice.wav")])
    ass_arg = ass.as_posix().replace(":", "\\:")
    vf = f"ass='{ass_arg}'" + (f":fontsdir='{Path(a.fontsdir).as_posix()}'" if a.fontsdir else "")
    vf += f",fade=t=in:st=0:d=0.6,fade=t=out:st={max(0, total-1.0):.2f}:d=1.0"
    cmd = ["ffmpeg", "-y", "-i", str(tmp / "video.mp4"), "-i", str(tmp / "voice.wav")]
    if a.music:
        cmd += ["-stream_loop", "-1", "-i", a.music, "-filter_complex",
                f"[2:a]volume={a.music_volume},afade=t=out:st={max(0,total-3):.2f}:d=3[m];[1:a][m]amix=inputs=2:duration=first:normalize=0[aout]",
                "-map", "0:v", "-map", "[aout]"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", str(out)]
    run(cmd)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"done: {out}  ({total/60:.1f} min)\n  captions: {stem}.hi.srt\n  chapters: {stem}.chapters.txt")


if __name__ == "__main__":
    main()
