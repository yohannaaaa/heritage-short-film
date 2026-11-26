import json, sys
from pathlib import Path
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

def validate(path=None):
    sb = json.loads((path or ROOT / "storyboard.json").read_text(encoding="utf-8"))
    schema = json.loads((ROOT / "schema" / "storyboard.schema.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(sb), key=lambda e: list(e.path))
    if errors:
        msg = "\n".join(f"- {'.'.join(map(str, e.path))}: {e.message}" for e in errors)
        raise SystemExit(f"Storyboard structure is invalid:\n{msg}")
    ids = [s["id"] for s in sb["shots"]]
    if len(ids) != len(set(ids)):
        raise SystemExit("Shot IDs must be unique.")
    total = sum(s["duration_seconds"] for s in sb["shots"])
    if total != sb["total_duration_seconds"]:
        raise SystemExit(f"Duration mismatch: declared {sb['total_duration_seconds']}s, shots sum to {total}s.")
    speakers = sb["audio"]["speakers"]
    for s in sb["shots"]:
        for d in s["dialogue"]:
            if d["speaker"] not in speakers:
                raise SystemExit(f"{s['id']}: speaker '{d['speaker']}' has no voice in audio.speakers.")
    return sb

if __name__ == "__main__":
    sb = validate()
    print(f"Storyboard is valid: {len(sb['shots'])} shots, {sb['total_duration_seconds']}s")