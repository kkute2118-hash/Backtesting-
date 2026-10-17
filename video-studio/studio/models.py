"""The Seedance models the studio can call, and the options each accepts.

Endpoint ids are as listed on fal.ai in October 2026. If fal renames one,
change it here; nothing else needs to know.
"""

V1_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"]
V2_RATIOS = ["auto"] + V1_RATIOS

MODELS = {
    "seedance-2.0": {
        "label": "Seedance 2.0",
        "note": "Best quality, native audio, up to 1080p",
        "text": "bytedance/seedance-2.0/text-to-video",
        "image": "bytedance/seedance-2.0/image-to-video",
        "options": {
            "resolution": ["720p", "480p", "1080p"],
            "duration": ["auto", "5", "8", "10"],
            "aspect_ratio": V2_RATIOS,
            "generate_audio": True,
            "seed": True,
        },
    },
    "seedance-2.0-fast": {
        "label": "Seedance 2.0 Fast",
        "note": "Quicker and cheaper drafts, up to 720p",
        "text": "bytedance/seedance-2.0/fast/text-to-video",
        "image": "bytedance/seedance-2.0/fast/image-to-video",
        "options": {
            "resolution": ["720p", "480p"],
            "duration": ["auto", "5", "8", "10"],
            "aspect_ratio": V2_RATIOS,
            "generate_audio": True,
            "seed": True,
        },
    },
    "seedance-1-pro": {
        "label": "Seedance 1.0 Pro",
        "note": "Silent clips, 1080p, start and end frames",
        "text": "fal-ai/bytedance/seedance/v1/pro/text-to-video",
        "image": "fal-ai/bytedance/seedance/v1/pro/image-to-video",
        "options": {
            "resolution": ["1080p", "720p", "480p"],
            "duration": ["5", "10"],
            "aspect_ratio": V1_RATIOS,
            "camera_fixed": True,
            "end_image": True,
            "seed": True,
        },
    },
    "seedance-1-lite": {
        "label": "Seedance 1.0 Lite",
        "note": "Cheapest, up to 720p",
        "text": "fal-ai/bytedance/seedance/v1/lite/text-to-video",
        "image": "fal-ai/bytedance/seedance/v1/lite/image-to-video",
        "options": {
            "resolution": ["720p", "480p"],
            "duration": ["5", "10"],
            "aspect_ratio": V1_RATIOS,
            "camera_fixed": True,
            "end_image": True,
            "seed": True,
        },
    },
}


def build_request(model_key, prompt, *, image_url=None, end_image_url=None,
                  resolution=None, duration=None, aspect_ratio=None,
                  seed=None, camera_fixed=False, generate_audio=None):
    """Return (endpoint, payload) for one generation, keeping only the
    options this model accepts. Raises ValueError on a bad choice."""
    if model_key not in MODELS:
        raise ValueError(f"unknown model {model_key!r}")
    m = MODELS[model_key]
    opts = m["options"]
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("prompt is empty")

    payload = {"prompt": prompt}
    for name, value in (("resolution", resolution), ("duration", duration),
                        ("aspect_ratio", aspect_ratio)):
        if value in (None, ""):
            continue
        if value not in opts[name]:
            raise ValueError(f"{m['label']} does not offer {name}={value!r}")
        payload[name] = value

    if image_url:
        payload["image_url"] = image_url
        # The source image sets the frame, so a ratio only applies to text.
        payload.pop("aspect_ratio", None)
        if end_image_url and opts.get("end_image"):
            payload["end_image_url"] = end_image_url
    if seed not in (None, "") and opts.get("seed"):
        payload["seed"] = int(seed)
    if camera_fixed and opts.get("camera_fixed"):
        payload["camera_fixed"] = True
    if generate_audio is not None and opts.get("generate_audio"):
        payload["generate_audio"] = bool(generate_audio)

    return m["image" if image_url else "text"], payload
