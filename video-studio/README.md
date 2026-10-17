# Seedance Studio

A small web app for making videos with ByteDance's **Seedance** models:
text to video, image to video (with an optional end frame), camera-move and
look presets, and a gallery of everything you've made.

It does not run Seedance itself. The model is closed, so the studio sends
each job to [fal.ai](https://fal.ai), which runs it and charges your fal
account per clip. Separate from the trading system; nothing in `backend/`
uses it.

## Run it

```bash
cd video-studio
pip install -r requirements.txt
export FAL_KEY=...            # from https://fal.ai/dashboard/keys
uvicorn studio.app:app --port 8800
```

Open http://localhost:8800. Finished videos are saved to `outputs/` and the
job list to `jobs.json` (both git-ignored; set `STUDIO_DATA` to keep them
elsewhere). Never commit your key: this repository is public.

## Models

| Choice | Good for |
|---|---|
| Seedance 2.0 | Best quality, native audio, up to 1080p |
| Seedance 2.0 Fast | Cheaper drafts, up to 720p |
| Seedance 1.0 Pro | Silent 1080p clips, start and end frames, locked camera |
| Seedance 1.0 Lite | Cheapest, up to 720p |

Prices change; check each model's page on fal.ai before a big batch. The
endpoint ids and the options each model accepts live in `studio/models.py`;
if fal renames an endpoint or adds a setting, change it there.

## Presets

Camera moves (dolly, orbit, crane, FPV drone, crash zoom...) and looks
(cinematic, anime, noir, VHS...) are plain sentences appended to your
prompt, in `studio/presets.py`. Add your own there.

## Tests

```bash
pip install pytest
python -m pytest -q tests
```

The tests replace fal.ai with a fake, so they need no key and cost nothing.
