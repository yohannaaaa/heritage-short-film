#!/usr/bin/env python3
"""Stage: assembly. Keyframes (or Wan clips) + narration + dialogue + score + English
subtitles + AI end card -> outputs/final/film_9x16.mp4 and film_16x9.mp4.

Picture per shot: outputs/clips/<shot>.mp4 if it exists (an animated clip, e.g. from Wan),
otherwise a Ken Burns pan/zoom over the selected keyframe. Shot length follows the speech:
a shot is lengthened if its audio would not fit. Subtitles are drawn with Pillow and overlaid
(no libass/drawtext needed). Music: outputs/music/score.(wav|mp3|flac|m4a); without it a
placeholder drone is used.

Usage: python pipeline/assemble.py [--aspect 9:16|16:9|both] [--author "Name"] [--music FILE] [--music-volume 0.5]
"""
import argparse, hashlib, json, math, os, subprocess, sys, textwrap, time
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from validate_storyboard import validate
from narration import items_for, wav_seconds, log_run, OUT as AUDIO, GAP, NARR_GAP, LEAD

ROOT = Path(__file__).resolve().parents[1]
KF, CLIPS = ROOT / "outputs" / "keyframes", ROOT / "outputs" / "clips"
SEG, FINAL, MUSIC = ROOT / "outputs" / "segments", ROOT / "outputs" / "final", ROOT / "outputs" / "music"
SEL, SUBS = ROOT / "outputs" / "selected.json", ROOT / "subtitles_en.json"
ASPECTS = {"9:16": (1080, 1920, "9x16"), "16:9": (1920, 1080, "16x9")}
FPS, END_CARD, TAIL = 24, 2.5, 0.4
MOTIONS = ["in", "pan_right", "out", "pan_left"]
LATIN_FONTS = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Helvetica.ttc",
               "/Library/Fonts/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
ETHIOPIC_FONTS = ["/System/Library/Fonts/Kefa.ttc", "/System/Library/Fonts/Supplemental/Kefa.ttc"]


def font(cands, env, size):
    p = os.environ.get(env)
    for c in ([p] if p else []) + cands:
        if c and Path(c).exists():
            return ImageFont.truetype(c, size)
    return None


def run(cmd, stage, key, params=None):
    t = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True)
    log_run(stage=stage, key=key, model="ffmpeg", params=params or {}, seed=None,
            latency_s=round(time.time() - t, 2), cost_usd=0.0, status="ok" if r.returncode == 0 else "error")
    if r.returncode:
        sys.exit(f"ffmpeg failed ({stage} {key}):\n{r.stderr[-1800:]}")


def fmt_srt(t):
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def timeline(sb):
    items = items_for(sb); shots, placements, t = [], [], 0.0
    for shot in sb["shots"]:
        mine = [i for i in items if i["shot"] == shot["id"]]
        cur, end_speech = t + LEAD, t
        for n, it in enumerate(mine):
            d = wav_seconds(AUDIO / f"{it['key']}.wav")
            placements.append(dict(key=it["key"], start=cur, seconds=d))
            end_speech = cur + d
            cur += d + (NARR_GAP if it["kind"] == "narration" and n < len(mine) - 1 else GAP)
        length = max(shot["duration_seconds"], (end_speech - t + TAIL) if mine else 0)
        length = math.ceil(length * FPS) / FPS
        shots.append(dict(id=shot["id"], scene=shot["scene"], start=t, length=length, declared=shot["duration_seconds"]))
        t += length
    return shots, placements, t


def segment(shot, idx, aspect, selected, manifest):
    W, H, tag = ASPECTS[aspect]
    SEG.mkdir(parents=True, exist_ok=True)
    clip = CLIPS / f"{shot['id']}.mp4"
    src = clip if clip.exists() else KF / f"{shot['id']}_c{selected.get(shot['id'], 0)}.png"
    if not src.exists():
        sys.exit(f"Missing picture for {shot['id']}: {src}")
    motion = MOTIONS[idx % len(MOTIONS)]
    n = int(round(shot["length"] * FPS))
    h = hashlib.sha256(src.read_bytes() + f"{W}x{H}{n}{motion}".encode()).hexdigest()[:16]
    out = SEG / f"{shot['id']}_{tag}.mp4"
    if out.exists() and manifest.get(out.name) == h:
        return out
    r = W / H
    crop = f"crop=ih*{r:.6f}:ih" if r < 1 else f"crop=iw:iw/{r:.6f}"
    if src.suffix == ".mp4":
        vf = f"{crop},scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS},tpad=stop_mode=clone:stop_duration={shot['length']},format=yuv420p"
        cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", vf]
    else:
        z = {"in": f"1+0.18*on/{n}", "out": f"1.18-0.18*on/{n}", "pan_right": "1.12", "pan_left": "1.12"}[motion]
        x = {"pan_right": f"(iw-iw/zoom)*on/{n}", "pan_left": f"(iw-iw/zoom)*(1-on/{n})"}.get(motion, "(iw-iw/zoom)/2")
        vf = (f"{crop},scale={2*W}:{2*H}:flags=lanczos,"
              f"zoompan=z='{z}':x='{x}':y='(ih-ih/zoom)/2':d={n}:s={W}x{H}:fps={FPS},setsar=1,format=yuv420p")
        cmd = ["ffmpeg", "-y", "-i", str(src), "-vf", vf]
    cmd += ["-frames:v", str(n), "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-preset", "medium", str(out)]
    run(cmd, "segment", f"{shot['id']}_{tag}", {"motion": motion if src.suffix != ".mp4" else "clip", "frames": n})
    manifest[out.name] = h
    return out


def subtitle_cards(placements, subs, W, H):
    wrap = 34 if W < H else 46
    cards = []
    for p in placements:
        text = subs[p["key"]]
        lines = textwrap.wrap(text, wrap)
        groups = ["\n".join(lines[i:i + 2]) for i in range(0, len(lines), 2)]
        total = sum(len(g) for g in groups); t = p["start"]
        for g in groups:
            d = p["seconds"] * len(g) / total
            cards.append(dict(text=g, start=t, end=t + d)); t += d
    return cards


def render_card(text, W, H, path):
    size = int(min(W, H) * 0.045)
    f = font(LATIN_FONTS, "FONT_PATH", size) or ImageFont.load_default()
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    lines = text.split("\n"); lh = int(size * 1.3); pad = int(size * 0.5)
    bw = max(d.textlength(l, font=f) for l in lines)
    y_bottom = int(H * (0.78 if W < H else 0.9))
    y_top = y_bottom - lh * len(lines) - pad
    d.rounded_rectangle([(W - bw) / 2 - pad, y_top, (W + bw) / 2 + pad, y_bottom], radius=pad, fill=(0, 0, 0, 150))
    for i, l in enumerate(lines):
        d.text(((W - d.textlength(l, font=f)) / 2, y_top + pad / 2 + i * lh), l, font=f, fill=(255, 255, 255, 255))
    img.save(path)


def render_endcard(sb, W, H, author, path):
    img = Image.new("RGB", (W, H), (18, 16, 14)); d = ImageDraw.Draw(img)
    u = min(W, H) / 1080
    rows = [("Made with AI", int(86 * u), (255, 255, 255)),
            (sb["english_title"], int(44 * u), (230, 200, 150))]
    am = font(ETHIOPIC_FONTS, "ETHIOPIC_FONT", int(44 * u))
    rows += [("Images: FLUX.2 klein   Voice: Gemini TTS   Music: ACE-Step 1.5", int(30 * u), (190, 190, 190)),
             ("All characters are fictional.", int(30 * u), (190, 190, 190))]
    if author:
        rows.append((f"Story, script and direction: {author}", int(30 * u), (190, 190, 190)))
    y = H * 0.36
    for text, size, color in rows:
        f = font(LATIN_FONTS, "FONT_PATH", size) or ImageFont.load_default()
        # shrink if too wide
        while d.textlength(text, font=f) > W * 0.9 and size > 12:
            size -= 2; f = font(LATIN_FONTS, "FONT_PATH", size) or f
        d.text(((W - d.textlength(text, font=f)) / 2, y), text, font=f, fill=color)
        y += size * 1.9
        if text == sb["english_title"] and am:
            t2 = sb["title"]
            d.text(((W - d.textlength(t2, font=am)) / 2, y - size * 0.4), t2, font=am, fill=(230, 200, 150)); y += size * 1.5
    img.save(path)


def build(aspect, sb, shots, placements, film_len, selected, subs, args):
    W, H, tag = ASPECTS[aspect]
    FINAL.mkdir(parents=True, exist_ok=True)
    work = SEG / f"work_{tag}"; work.mkdir(parents=True, exist_ok=True)
    mpath = SEG / "manifest.json"
    manifest = json.loads(mpath.read_text()) if mpath.exists() else {}
    segs = [segment(s, i, aspect, selected, manifest) for i, s in enumerate(shots)]
    mpath.write_text(json.dumps(manifest, indent=2))
    ec_png, ec_mp4 = work / "endcard.png", work / "endcard.mp4"
    render_endcard(sb, W, H, args.author, ec_png)
    run(["ffmpeg", "-y", "-loop", "1", "-i", str(ec_png), "-t", str(END_CARD), "-vf",
         f"fade=t=in:st=0:d=0.5,fade=t=out:st={END_CARD-0.7}:d=0.7,setsar=1,format=yuv420p", "-r", str(FPS),
         "-c:v", "libx264", "-crf", "18", str(ec_mp4)], "endcard", tag)
    lst = work / "concat.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in segs + [ec_mp4]))
    total = film_len + END_CARD

    cards = subtitle_cards(placements, subs, W, H)
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
    fc, last = [], "0:v"
    for i, c in enumerate(cards):
        png = work / f"sub_{i:02d}.png"; render_card(c["text"], W, H, png)
        cmd += ["-i", str(png)]
        fc.append(f"[{last}][{i+1}:v]overlay=0:0:enable='between(t,{c['start']:.3f},{c['end']:.3f})'[s{i}]")
        last = f"s{i}"
    base = len(cards) + 1
    labels = []
    for n, p in enumerate(placements):
        cmd += ["-i", str(AUDIO / f"{p['key']}.wav")]
        ms = int(p["start"] * 1000)
        fc.append(f"[{base+n}:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms}[v{n}]")
        labels.append(f"[v{n}]")
    mi = base + len(placements)
    score = Path(args.music) if args.music else next((p for e in ("wav", "mp3", "flac", "m4a") for p in [MUSIC / f"score.{e}"] if p.exists()), None)
    if score:
        cmd += ["-stream_loop", "-1", "-i", str(score)]
        mus = f"[{mi}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.music_volume}"
    else:
        print("  (no score found in outputs/music/ - using the placeholder drone)")
        cmd += ["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000"]
        mus = f"[{mi}:a][{mi+1}:a]amix=inputs=2:normalize=0,volume=0.08,aformat=sample_rates=48000:channel_layouts=stereo"
    fc.append(f"{mus},atrim=0:{total:.3f},afade=t=in:st=0:d=1.5,afade=t=out:st={total-3:.3f}:d=3[m]")
    fc.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest,apad=whole_dur={total:.3f},asplit=2[va][vb]")
    fc.append("[m][va]sidechaincompress=threshold=0.02:ratio=6:attack=300:release=1500[md]")
    fc.append(f"[vb][md]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-14:TP=-1:LRA=11,atrim=0:{total:.3f}[a]")
    out = FINAL / f"film_{tag}.mp4"
    cmd += ["-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", "[a]", "-t", f"{total:.3f}",
            "-c:v", "libx264", "-crf", "19", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS),
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
            "-metadata", "title=" + sb["english_title"], "-metadata", "comment=Made with AI (images, voice, music generated by AI models)",
            str(out)]
    run(cmd, "assemble", tag, {"total_s": round(total, 2), "subtitle_cards": len(cards), "score": str(score) if score else "placeholder"})
    srt = []
    for i, c in enumerate(cards, 1):
        srt.append(f"{i}\n{fmt_srt(c['start'])} --> {fmt_srt(c['end'])}\n{c['text']}\n")
    (FINAL / f"film_{tag}.en.srt").write_text("\n".join(srt), encoding="utf-8")
    print(f"  wrote {out}  ({total:.1f}s)")
    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aspect", default="both", choices=["both", "9:16", "16:9"])
    ap.add_argument("--author", default=os.environ.get("AUTHOR_NAME", ""))
    ap.add_argument("--music"); ap.add_argument("--music-volume", type=float, default=0.5)
    args = ap.parse_args()
    sb = validate()
    selected = json.loads(SEL.read_text()) if SEL.exists() else {}
    subs = json.loads(SUBS.read_text(encoding="utf-8"))
    missing = [i["key"] for i in items_for(sb) if not (AUDIO / f"{i['key']}.wav").exists()]
    nosub = [i["key"] for i in items_for(sb) if i["key"] not in subs]
    if missing: sys.exit(f"Missing audio: {missing}. Run pipeline/narration.py")
    if nosub: sys.exit(f"Missing English subtitles in subtitles_en.json for: {nosub}")
    shots, placements, film_len = timeline(sb)
    for s in shots:
        if s["length"] > s["declared"] + 0.01:
            print(f"  {s['id']}: lengthened {s['declared']}s -> {s['length']:.2f}s to fit the speech")
    total = 0
    for a in (["9:16", "16:9"] if args.aspect == "both" else [args.aspect]):
        print(f"Building {a} ...")
        total = build(a, sb, shots, placements, film_len, selected, subs, args)
    if not 60 <= total <= 90:
        print(f"WARNING: film is {total:.1f}s; the brief asks for 60-90s. Shorten shot durations in storyboard.json.")


if __name__ == "__main__":
    main()