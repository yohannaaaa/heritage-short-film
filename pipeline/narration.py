#!/usr/bin/env python3
"""Stage: narration + dialogue -> one WAV per line (Gemini TTS).

Reads storyboard.json, writes outputs/audio/<shot>_n<i>.wav (narration) and
<shot>_d<i>.wav (dialogue). Cached by a hash of (model, text, voice, style):
re-running only regenerates lines you changed. Every call is logged to runs.jsonl.

Usage: python pipeline/narration.py [--shot shot_06] [--force]
"""
import argparse, base64, hashlib, io, json, os, sys, time, wave
from pathlib import Path
import requests

sys.path.insert(0, str(Path(__file__).parent))
from validate_storyboard import validate

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "audio"
RUNS = ROOT / "runs.jsonl"
MANIFEST = OUT / "manifest.json"
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GAP, NARR_GAP, LEAD = 0.35, 1.2, 0.3   # seconds, shared with radio_cut.py


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def log_run(**row):
    row["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with open(RUNS, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def items_for(sb):
    """Flatten the storyboard into ordered audio items. A newline in narration_am = separate clip + longer pause."""
    a, out = sb["audio"], []
    for shot in sb["shots"]:
        segs = [s.strip() for s in shot["narration_am"].split("\n") if s.strip()]
        for i, text in enumerate(segs):
            out.append(dict(key=f"{shot['id']}_n{i}", shot=shot["id"], kind="narration", text=text,
                            voice=a["narration"]["voice"],
                            style=shot.get("narration_style", a["narration"]["style"])))
        for i, d in enumerate(shot["dialogue"]):
            sp = a["speakers"][d["speaker"]]
            out.append(dict(key=f"{shot['id']}_d{i}", shot=shot["id"], kind="dialogue", text=d["line"],
                            voice=sp["voice"], style=d.get("style", sp["style"]), speaker=d["speaker"]))
    return out


def wav_seconds(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def call_tts(model, text, voice, style, key):
    part = {"text": text}
    if style:
        part["speech_metadata"] = {"style": style}
    body = {"contents": [{"parts": [part]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    for attempt in range(1, 5):
        r = requests.post(API.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=180)
        if r.status_code == 400 and "speech_metadata" in r.text and "speech_metadata" in body["contents"][0]["parts"][0]:
            # schema mismatch: retry without style rather than speaking directions aloud
            body["contents"][0]["parts"][0].pop("speech_metadata")
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(15 * attempt)
            continue
        r.raise_for_status()
        inline = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]
        data = base64.b64decode(inline["data"])
        if data[:4] != b"RIFF":  # headerless PCM (older models): 24 kHz, 16-bit, mono
            buf = io.BytesIO()
            with wave.open(buf, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(data)
            data = buf.getvalue()
        return data
    raise RuntimeError(f"TTS failed after retries: {r.status_code} {r.text[:300]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot"); ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    load_env()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("Set GEMINI_API_KEY in .env or your environment.")
    sb = validate()
    model = sb["audio"]["tts_model"]
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    failed = 0
    for it in items_for(sb):
        if args.shot and it["shot"] != args.shot:
            continue
        path = OUT / f"{it['key']}.wav"
        h = hashlib.sha256(json.dumps([model, it["text"], it["voice"], it["style"]], ensure_ascii=False).encode()).hexdigest()[:16]
        if not args.force and path.exists() and manifest.get(it["key"]) == h:
            print(f"  cached  {it['key']}")
            continue
        t = time.time()
        try:
            path.write_bytes(call_tts(model, it["text"], it["voice"], it["style"], key))
            manifest[it["key"]] = h
            MANIFEST.write_text(json.dumps(manifest, indent=2))
            sec = wav_seconds(path)
            log_run(stage="narration", key=it["key"], model=model, params={"voice": it["voice"], "style": it["style"]},
                    seed=None, chars=len(it["text"]), audio_seconds=round(sec, 2),
                    latency_s=round(time.time() - t, 2), cost_usd=0.0, status="ok")
            print(f"  made    {it['key']}  {sec:.1f}s")
        except Exception as e:
            failed += 1
            log_run(stage="narration", key=it["key"], model=model, params={"voice": it["voice"]}, seed=None,
                    latency_s=round(time.time() - t, 2), cost_usd=0.0, status="error", error=str(e)[:300])
            print(f"  FAILED  {it['key']}: {e}")
    timing_report(sb)
    sys.exit(1 if failed else 0)


def timing_report(sb):
    print("\nShot timing (spoken audio vs shot length):")
    by_shot = {}
    for it in items_for(sb):
        p = OUT / f"{it['key']}.wav"
        if p.exists():
            by_shot.setdefault(it["shot"], []).append((it, wav_seconds(p)))
    report = {}
    for s in sb["shots"]:
        clips = by_shot.get(s["id"], [])
        total = LEAD
        for n, (it, d) in enumerate(clips):
            total += d + (NARR_GAP if it["kind"] == "narration" and n < len(clips) - 1 else GAP)
        total -= GAP if clips else 0
        report[s["id"]] = {"shot_seconds": s["duration_seconds"], "audio_seconds": round(total, 2)}
        flag = "  <-- OVER, lengthen shot or trim line" if clips and total > s["duration_seconds"] else ""
        print(f"  {s['id']}: {total:5.1f}s of {s['duration_seconds']}s{flag}" if clips else f"  {s['id']}: (no speech)")
    (OUT / "timing.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()