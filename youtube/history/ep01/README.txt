EPISODE 1 (cartoon) - सिंधु घाटी सभ्यता, told by गप्पू काका
Everything here is free. Result: a ready-to-upload ~10-minute 1080p video.

ONE-TIME SETUP (Windows)
  1. Install Python 3 from python.org (tick "Add Python to PATH").
  2. Install ffmpeg:  winget install ffmpeg      (or download from ffmpeg.org)
  3. In this folder:  pip install edge-tts pillow

STEP 1 - PICTURES (free)  -> folder "images"
  Open image_prompts.txt. First make the CHARACTER SHEET of Gappu Kaka in the
  Gemini app or Google AI Studio (free). Then for each scene paste the prompt,
  attach the character sheet when the scene has Gappu Kaka, and save the picture
  as s01.png, s02.png ... s71.png. Other free options: Meta AI, Bing Image Creator.

STEP 2 - BUILD (voice is automatic and free)
  python make_episode.py script.json --images images --out episode01.mp4 --burn-subs
  - It creates natural Hindi voices with Microsoft's free neural voices
    (Madhur for Gappu Kaka, Swara for women) in the "voice" folder, then the video.
  - Don't like one line? Delete voice\s12.mp3, change the text in script.json, run again.
  - Your own voice instead: record each line from voice_lines.txt as voice\s01.mp3 ...
    and add --no-tts.
  - Background music (free, YouTube Audio Library):  --music music.mp3
  - Mac: add --font "Kohinoor Devanagari"

STEP 3 - UPLOAD  (youtube_upload.txt)
  Title, description, tags; paste chapter times from episode01.chapters.txt;
  upload episode01.hi.srt as Hindi subtitles if you did not use --burn-subs.
