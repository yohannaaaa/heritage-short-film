#!/usr/bin/env python3
"""One-off helper: adds the "visual" block (style, references, per-shot references)
to storyboard.json without touching anything else you edited. Edit the prompts
afterwards directly in storyboard.json. Use --force to overwrite an existing block."""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SB = ROOT / "storyboard.json"

LOCK = {
    "mother": "a fictional Ethiopian woman in her early forties with warm brown skin, shoulder-length dark curly hair and kind expressive eyes",
    "uncle": "a fictional Ethiopian man in his forties with brown skin, short dark hair, a short neat beard and a friendly expressive face",
    "sisters": "two fictional Ethiopian teenage sisters, the older with long braided hair and the younger with a short curly afro, both with warm brown skin",
    "adult_sisters": "the same two sisters as adults in their late twenties, the older with long braided hair and the younger with a short curly afro, both with warm brown skin",
}

VISUAL = {
    "image_model": "@cf/black-forest-labs/flux-2-klein-4b",
    "size": {"width": 1024, "height": 1024},
    "reference_size": 512,
    "candidates": 2,
    "base_seed": 2026,
    "same_seed": True,
    "daily_neuron_cap": 8500,
    "anchors": {
        "childhood_memory": "shot_06",
        "passage_of_time": "shot_06",
        "present_day": "shot_11",
        "emotional_ending": "shot_11"
    },
    "style_blocks": {
        "childhood_memory": "Cinematic realistic film still, natural skin texture, 35mm film grain, shallow depth of field, warm golden amber light, cozy lived-in Ethiopian family home, genuine candid expressions.",
        "passage_of_time": "Cinematic realistic film still, soft light fading from warm amber toward neutral tones, quiet nostalgic mood, shallow depth of field, natural textures.",
        "present_day": "Cinematic realistic film still, cooler neutral lighting, quiet modern Ethiopian home, muted colours, calm composition, natural skin texture, realistic and comfortable, not gloomy.",
        "emotional_ending": "Cinematic realistic film still, soft neutral-to-warm light, intimate framing, thoughtful nostalgic expression, shallow depth of field, natural skin texture."
    },
    "common_suffix": "Subject centred in the frame with generous margins so the image can be cropped to vertical and horizontal. No text, no captions, no logos, no watermark.",
    "references": {
        "mother": {"lock": LOCK["mother"], "prompt": "Head-and-shoulders character reference portrait of " + LOCK["mother"] + ", warm energetic smile, modest everyday home clothing, plain soft background, front-facing, natural light, realistic photo."},
        "uncle": {"lock": LOCK["uncle"], "prompt": "Head-and-shoulders character reference portrait of " + LOCK["uncle"] + ", casual everyday shirt, plain soft background, front-facing, natural light, realistic photo."},
        "sisters": {"lock": LOCK["sisters"], "prompt": "Character reference photo of " + LOCK["sisters"] + ", standing close side by side, playful and energetic, casual everyday clothes, plain soft background, faces clearly visible, front-facing, natural light, realistic photo."},
        "adult_sisters": {"from": ["sisters"], "lock": LOCK["adult_sisters"], "prompt": "Using image 0 for identity: " + LOCK["adult_sisters"] + ", standing close side by side, modern casual clothes, plain soft background, faces clearly visible, front-facing, natural light, realistic photo."},
        "home": {"prompt": "Interior of a cozy lived-in Ethiopian family home: living room with a couch and television, a dining area with a large table, family photographs on the wall, warm afternoon light, no people, realistic photo."}
    },
    "shot_refs": {
        "shot_01": ["home"],
        "shot_02": ["sisters", "home"],
        "shot_03": ["sisters", "home"],
        "shot_04": ["sisters", "home"],
        "shot_05": ["mother", "uncle", "sisters"],
        "shot_06": ["mother", "uncle", "sisters"],
        "shot_07": ["sisters", "adult_sisters"],
        "shot_08": ["home"],
        "shot_09": ["mother", "uncle", "adult_sisters"],
        "shot_10": ["adult_sisters", "uncle"],
        "shot_11": ["mother", "uncle", "adult_sisters"],
        "shot_12": ["adult_sisters", "home"]
    }
}

if __name__ == "__main__":
    sb = json.loads(SB.read_text(encoding="utf-8"))
    if "visual" in sb and "--force" not in sys.argv:
        sys.exit('storyboard.json already has a "visual" block (use --force to overwrite).')
    sb["visual"] = VISUAL
    SB.write_text(json.dumps(sb, ensure_ascii=False, indent=2), encoding="utf-8")
    print('Added "visual" block to storyboard.json')