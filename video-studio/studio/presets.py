"""Shot presets: camera moves and looks that get appended to the prompt.
Seedance follows plain-language camera directions, so a preset is text."""

CAMERA = {
    "none": "",
    "dolly-in": "Slow dolly in toward the subject.",
    "dolly-out": "Slow dolly out, revealing the surroundings.",
    "orbit": "The camera orbits 180 degrees around the subject.",
    "crane-up": "Crane shot rising up and over the scene.",
    "fpv-drone": "Fast FPV drone flight, swooping low and banking through the scene.",
    "handheld": "Handheld camera with natural shake, documentary feel.",
    "whip-pan": "Quick whip pan to the subject.",
    "crash-zoom": "Sudden crash zoom onto the subject's face.",
    "tracking": "Tracking shot following the subject from the side.",
    "static": "Locked-off static camera.",
}

STYLE = {
    "none": "",
    "cinematic": "Cinematic, anamorphic lens, shallow depth of field, film grain, teal and orange grade.",
    "commercial": "Clean high-end commercial look, soft studio lighting, crisp detail.",
    "anime": "Japanese anime style, hand-drawn cel shading, vibrant colors.",
    "noir": "Black and white film noir, hard shadows, venetian-blind light.",
    "vhs": "1990s VHS camcorder footage, tracking lines, washed colors.",
    "golden-hour": "Golden hour sunlight, warm backlight, lens flare.",
    "neon": "Rainy night, neon reflections, cyberpunk palette.",
    "claymation": "Stop-motion claymation, handmade textures.",
}


def apply(prompt, camera="none", style="none"):
    parts = [prompt.strip(), CAMERA.get(camera, ""), STYLE.get(style, "")]
    return " ".join(p for p in parts if p)
