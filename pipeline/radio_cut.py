#!/usr/bin/env python3
"""Stage: radio cut = narration + dialogue over a placeholder music bed on a black screen.

Places each shot's audio at the shot's start. If a shot's speech overruns, the
next shot is pushed later and the shift is reported, so you learn the real timing.
Output: outputs/radio_cut/radio_cut.mp4 and radio_cut_timeline.json.
"""
import json, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validate_storyboard import validate
from narration import items_for, wav_seconds, log_run, OUT as AUDIO, GAP, NARR_GAP, LEAD

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "outputs" / "radio_cut"


def main():
    sb = validate()
    DEST.mkdir(parents=True, exist_ok=True)
    items = items_for(sb)
    missing = [i["key"] for i in items if not (AUDIO / f"{i['key']}.wav").exists()]
    if missing:
        sys.exit(f"Missing audio, run pipeline/narration.py first: {missing}")

    placements, cursor, shot_start, shifts = [], 0.0, 0.0, {}
    for shot in sb["shots"]:
        mine = [i for i in items if i["shot"] == shot["id"]]
        cur = max(shot_start + LEAD, cursor)
        for n, it in enumerate(mine):
            d = wav_seconds(AUDIO / f"{it['key']}.wav")
            placements.append({"key": it["key"], "start": round(cur, 2), "seconds": round(d, 2)})
            cur += d + (NARR_GAP if it["kind"] == "narration" and n < len(mine) - 1 else GAP)
        if mine:
            cursor = cur
            over = cur - GAP - (shot_start + shot["duration_seconds"])
            if over > 0:
                shifts[shot["id"]] = round(over, 2)
        shot_start += shot["duration_seconds"]
    total = max(shot_start, cursor) + 1.5
    (DEST / "radio_cut_timeline.json").write_text(json.dumps({"placements": placements, "overruns_s": shifts, "total_s": round(total, 2)}, indent=2))

    cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=720x1280:r=24:d={total}",
           "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000",
           "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000"]
    fc = [f"[1][2]amix=inputs=2:normalize=0,volume=0.12,tremolo=f=0.3:d=0.5,aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total}[m]"]
    labels = []
    for n, p in enumerate(placements):
        cmd += ["-i", str(AUDIO / f"{p['key']}.wav")]
        ms = int(p["start"] * 1000)
        fc.append(f"[{n+3}]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms}[v{n}]")
        labels.append(f"[v{n}]")
    fc.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,apad=whole_dur={total},asplit=2[v1][v2]")
    fc.append("[m][v1]sidechaincompress=threshold=0.02:ratio=6:attack=300:release=1500[md]")
    fc.append(f"[v2][md]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-14:TP=-1:LRA=11,atrim=0:{total}[a]")
    out = DEST / "radio_cut.mp4"
    cmd += ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-t", str(total),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(out)]
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    log_run(stage="radio_cut", key="radio_cut", model="ffmpeg", params={"clips": len(placements), "total_s": round(total, 2)},
            seed=None, latency_s=round(time.time() - t, 2), cost_usd=0.0, status="ok" if r.returncode == 0 else "error")
    if r.returncode:
        sys.exit(r.stderr[-1500:])
    print(f"Radio cut: {out}  ({total:.1f}s, declared {sb['total_duration_seconds']}s)")
    for k, v in shifts.items():
        print(f"  {k} speech overruns its shot by {v}s -> shorten the line or lengthen the shot")


if __name__ == "__main__":
    main()