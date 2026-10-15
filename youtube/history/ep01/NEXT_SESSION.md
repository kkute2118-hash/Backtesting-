# Episode 1 (सिंधु घाटी सभ्यता, told by गप्पू काका): finish the video

Everything except the voice is done: script.json (71 scenes), images/ (drawn
by tools/scenes.py), make_episode.py (builds the 1080p video), youtube_upload.txt.

The voice must be natural Hindi (eSpeak/MBROLA were rejected). Google's Gemini
API is reachable from cloud sessions, so with GEMINI_API_KEY set in the
environment:

    pip install pillow
    cd youtube/history/ep01
    python tools/gemini_voice.py script.json voice_gemini            # 10 chapter files
    python make_episode.py script.json --images images --voice voice_gemini \
        --no-tts --burn-subs --font FreeSans --out out/episode01.mp4

Voices (same set MoneyPrinterTurbo uses): Algenib = Gappu Kaka, Sulafat = women,
Puck = worker/trader; model gemini-2.5-flash-preview-tts (free tier). Never set up Google billing:
the owner wants this free.
Then compress under 30 MB for sending (two-pass x264 ~360k) and update the
chapter times in youtube_upload.txt from out/episode01.chapters.txt.
Optional background music: MoneyPrinterTurbo fork, resource/songs/*.mp3 (--music, check its licence first).
