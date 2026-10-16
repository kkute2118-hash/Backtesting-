#!/usr/bin/env python3
"""Cut vertical Shorts / Reels (1080x1920) from a finished episode.

    python make_shorts.py EPISODE_DIR

EPISODE_DIR holds script.json, the chapter voices (voice/ or voice_gemini/),
the full video out/episodeNN.mp4 and shorts.json:

    {"episode_title": "...", "shorts": [
       {"from": "s08", "to": "s11", "hook": "big text on top",
        "cta": "बाकी कहानी पूरे वीडियो में", "title": "YouTube title", "hashtags": "#..."}]}

Each Short plays scenes from..to of the full video (cut at pauses in the voice, so no
word is chopped), with the hook on top, the episode in the middle over a blurred copy
of itself, and the call to action at the bottom. Writes out/shorts/epNN_shortN.mp4 and
out/shorts/epNN_shorts_upload.txt (episode-prefixed, so files from different episodes
never collide when sent or uploaded). Pick moments that end on a question, so viewers go to
the full video for the answer.
"""
import json, re, subprocess, sys
from pathlib import Path

FONT = "FreeSans"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit("ffmpeg failed:\n" + r.stderr[-1500:])
    return r


def duration(p):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", str(p)]).stdout)


def scene_times(ep, sc):
    """Same timing make_episode.py uses for chapter-level voices."""
    vdir = next(d for d in (ep / "voice", ep / "voice_gemini") if d.exists())
    t, times = 0.0, {}
    for ch in sc["chapters"]:
        cd = duration(vdir / f"{ch['id']}.wav") + 0.9
        tc = sum(len(s["text"]) for s in ch["shots"])
        for s in ch["shots"]:
            d = cd * len(s["text"]) / tc
            times[s["id"]] = (t, t + d); t += d
    return times


def silences(video):
    err = run(["ffmpeg", "-i", str(video), "-af", "silencedetect=noise=-38dB:d=0.25", "-f", "null", "-"]).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", err)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    return [(a + b) / 2 for a, b in zip(starts, ends)]


def snap(t, gaps, window=2.0):
    near = [g for g in gaps if abs(g - t) <= window]
    return min(near, key=lambda g: abs(g - t)) if near else t


def ass_time(t):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def srt_entries(path):
    out = []
    for block in Path(path).read_text(encoding="utf-8").strip().split("\n\n"):
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        def secs(x):
            h, m, rest = x.split(":"); s_, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(s_) + int(ms) / 1000
        a, b = [secs(x.strip()) for x in lines[1].split("-->")]
        out.append((a, b, " ".join(lines[2:])))
    return out


def wrap(text, n=16):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur); cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return r"\N".join(lines)


def main():
    ep = Path(sys.argv[1]).resolve()
    sc = json.load(open(ep / "script.json", encoding="utf-8"))
    spec = json.load(open(ep / "shorts.json", encoding="utf-8"))
    video = sorted((ep / "out").glob("episode??.mp4"))[0]
    out = ep / "out" / "shorts"; out.mkdir(parents=True, exist_ok=True)
    times, gaps = scene_times(ep, sc), silences(video)
    caps = srt_entries(video.with_suffix(".hi.srt"))
    notes = []
    for i, s in enumerate(spec["shorts"], 1):
        a = snap(times[s["from"]][0], gaps); b = snap(times[s["to"]][1], gaps)
        dur = b - a
        cta_from = max(0.0, dur - 4.0)
        ass = out / f"short{i}.ass"
        ass.write_text(f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hook,{FONT},86,&H0060DCFF,&H00FFFFFF,&H00101010,&HB0000000,1,0,0,0,100,100,0,0,1,7,3,8,60,60,190,1
Style: Brand,{FONT},44,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,1,0,0,0,100,100,0,0,1,4,0,8,60,60,90,1
Style: Cap,{FONT},62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,6,2,2,70,70,480,1
Style: Cta,{FONT},64,&H00FFFFFF,&H00FFFFFF,&H00101010,&HC0202080,1,0,0,0,100,100,0,0,3,18,0,2,70,70,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 1,0:00:00.00,{ass_time(dur)},Brand,,0,0,0,,History Tracker · गप्पू काका
Dialogue: 1,0:00:00.00,{ass_time(dur)},Hook,,0,0,0,,{{\\fad(200,0)}}{wrap(s['hook'])}
Dialogue: 2,{ass_time(cta_from)},{ass_time(dur)},Cta,,0,0,0,,{{\\fad(250,0)\\fscx85\\fscy85\\t(0,250,\\fscx100\\fscy100)}}{wrap(s['cta'], 20)}
""" + "".join(
            f"Dialogue: 0,{ass_time(max(0, x - a))},{ass_time(min(dur, y - a))},Cap,,0,0,0,,{wrap(txt, 22)}\n"
            for x, y, txt in caps if y > a and x < b), encoding="utf-8")
        arg = ass.as_posix().replace(":", r"\:")
        fc = (f"[0:v]split=2[bg][fg];"
              f"[bg]scale=-2:1920,crop=1080:1920,boxblur=28:2,eq=brightness=-0.18[bgb];"
              f"[fg]scale=1242:-2,crop=1080:ih[fgc];"
              f"[bgb][fgc]overlay=0:(H-h)/2-40,ass='{arg}',fade=t=out:st={max(0, dur-0.4):.2f}:d=0.4[v]")
        dst = out / f"{ep.name}_short{i}.mp4"
        run(["ffmpeg", "-y", "-ss", f"{a:.2f}", "-t", f"{dur:.2f}", "-i", str(video), "-filter_complex", fc,
             "-map", "[v]", "-map", "0:a", "-af", f"afade=t=out:st={max(0, dur-0.4):.2f}:d=0.4",
             "-c:v", "libx264", "-preset", "medium", "-crf", "21", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)])
        ass.unlink()
        print(f"short{i}: {s['from']}-{s['to']}  {dur:.1f}s  {dst.name}")
        notes.append(f"=== {ep.name}_short{i}.mp4 ({dur:.0f} s) ===\nTITLE: {s['title']} #shorts\n"
                     f"DESCRIPTION: {s['hook']} पूरी कहानी: \"{spec['episode_title']}\" (History Tracker चैनल पर, लिंक ऊपर/कमेंट में)\n"
                     f"{s['hashtags']} #shorts #HistoryTracker #भारतकाइतिहास\n"
                     f"YOUTUBE: set 'Related video' to the full episode. INSTAGRAM/FACEBOOK REELS: same file, same caption.\n")
    (out / f"{ep.name}_shorts_upload.txt").write_text("\n".join(notes), encoding="utf-8")


if __name__ == "__main__":
    main()
