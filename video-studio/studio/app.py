"""Seedance Studio web server.

    FAL_KEY=... uvicorn studio.app:app --port 8800

Jobs live in jobs.json and finished videos in outputs/, both next to this
package's parent folder unless STUDIO_DATA points elsewhere.
"""
import base64
import json
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import models, presets
from .fal import FalClient, FalError

DATA = Path(os.environ.get("STUDIO_DATA", Path(__file__).resolve().parent.parent))
OUT = DATA / "outputs"
JOBS = DATA / "jobs.json"
MAX_IMAGE = 10 * 1024 * 1024

app = FastAPI(title="Seedance Studio")
fal = FalClient()
_lock = threading.Lock()


def _load():
    try:
        return json.loads(JOBS.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _save(jobs):
    JOBS.parent.mkdir(parents=True, exist_ok=True)
    tmp = JOBS.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, indent=1))
    tmp.replace(JOBS)


async def _data_uri(upload):
    if not upload or not upload.filename:
        return None
    raw = await upload.read()
    if len(raw) > MAX_IMAGE:
        raise HTTPException(413, "image is larger than 10 MB")
    kind = upload.content_type or "image/png"
    if not kind.startswith("image/"):
        raise HTTPException(400, "upload an image file")
    return f"data:{kind};base64,{base64.b64encode(raw).decode()}"


@app.get("/api/models")
def list_models():
    return {"models": models.MODELS, "camera": list(presets.CAMERA),
            "style": list(presets.STYLE), "has_key": bool(fal.key)}


@app.post("/api/generate")
async def generate(model: str = Form(...), prompt: str = Form(...),
                   camera: str = Form("none"), style: str = Form("none"),
                   resolution: str = Form(""), duration: str = Form(""),
                   aspect_ratio: str = Form(""), seed: str = Form(""),
                   camera_fixed: bool = Form(False),
                   generate_audio: bool = Form(True),
                   image: UploadFile | None = File(None),
                   end_image: UploadFile | None = File(None)):
    full_prompt = presets.apply(prompt, camera, style)
    try:
        endpoint, payload = models.build_request(
            model, full_prompt, image_url=await _data_uri(image),
            end_image_url=await _data_uri(end_image), resolution=resolution,
            duration=duration, aspect_ratio=aspect_ratio, seed=seed,
            camera_fixed=camera_fixed, generate_audio=generate_audio)
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        q = fal.submit(endpoint, payload)
    except FalError as e:
        raise HTTPException(502, str(e))

    job = {"id": uuid.uuid4().hex[:12], "created": time.time(),
           "model": model, "endpoint": endpoint, "prompt": prompt,
           "full_prompt": full_prompt, "camera": camera, "style": style,
           "mode": "image" if "image_url" in payload else "text",
           "settings": {k: v for k, v in payload.items()
                        if k not in ("prompt", "image_url", "end_image_url")},
           "status": "IN_QUEUE", **q}
    with _lock:
        jobs = _load()
        jobs[job["id"]] = job
        _save(jobs)
    return job


def _refresh(job):
    """Ask fal how a job is doing; download the video once it's done."""
    if job["status"] in ("COMPLETED", "FAILED"):
        return job
    try:
        s = fal.status(job["status_url"])
        job["status"] = s.get("status", job["status"])
        job["queue_position"] = s.get("queue_position")
        if job["status"] == "COMPLETED":
            res = fal.result(job["response_url"])
            video = (res.get("video") or {}).get("url")
            if not video:
                raise FalError(f"no video in result: {res}")
            OUT.mkdir(parents=True, exist_ok=True)
            fal.download(video, OUT / f"{job['id']}.mp4")
            job["file"] = f"{job['id']}.mp4"
            job["seed_used"] = res.get("seed")
            job["finished"] = time.time()
    except FalError as e:
        job["status"], job["error"] = "FAILED", str(e)
    return job


@app.get("/api/jobs")
def list_jobs():
    with _lock:
        jobs = _load()
    return sorted(jobs.values(), key=lambda j: j["created"], reverse=True)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with _lock:
        jobs = _load()
        if job_id not in jobs:
            raise HTTPException(404, "no such job")
        job = _refresh(jobs[job_id])
        jobs[job_id] = job
        _save(jobs)
    return job


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    with _lock:
        jobs = _load()
        job = jobs.pop(job_id, None)
        _save(jobs)
    if job and job.get("file"):
        (OUT / job["file"]).unlink(missing_ok=True)
    return {"deleted": bool(job)}


@app.get("/videos/{name}")
def video(name: str):
    path = (OUT / name).resolve()
    if path.parent != OUT.resolve() or not path.is_file():
        raise HTTPException(404, "no such video")
    return FileResponse(path, media_type="video/mp4")


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True))
