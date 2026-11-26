#!/usr/bin/env python3
"""Stage: reference images + keyframes (FLUX.2 klein 4B on Cloudflare Workers AI).

Workflow
  1. python pipeline/keyframes.py --refs                  # character/home reference candidates
  2. look in outputs/references/, then pick:  --select mother 1   (candidate index)
  3. python pipeline/keyframes.py --shot shot_06          # ANCHOR shot of the childhood scenes
  4. look in outputs/keyframes/, pick:  --select shot_06 1
  5. python pipeline/keyframes.py --shot shot_11          # ANCHOR shot of the present-day scenes
  6. pick:  --select shot_11 1
  7. python pipeline/keyframes.py                         # all other shots; each gets its character
                                                          # references AND its scene's anchor frame as input
  8. pick the best candidate of each shot:  --select shot_02 1

Free-tier safety: every call's estimated neuron cost is logged to runs.jsonl; the script
stops BEFORE a call that would pass daily_neuron_cap (counted per UTC day; Cloudflare resets
at 00:00 UTC = 03:00 Addis Ababa). A 429 / quota reply stops the whole run (no retry loop).
Use --dry-run to see the plan and the estimated cost without calling anything.
"""
import argparse, base64, hashlib, io, json, math, os, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from validate_storyboard import validate
from narration import load_env, log_run, RUNS

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "outputs" / "references"
KF = ROOT / "outputs" / "keyframes"
SEL = ROOT / "outputs" / "selected.json"
MANIFEST = ROOT / "outputs" / "image_manifest.json"
NEURONS_OUT_TILE, NEURONS_IN_IMAGE = 26.05, 5.37   # Cloudflare list price, flux-2-klein-4b


class QuotaStop(Exception):
    pass


def tiles(w, h):
    return math.ceil(w / 512) * math.ceil(h / 512)


def estimate(w, h, n_inputs):
    return tiles(w, h) * NEURONS_OUT_TILE + n_inputs * NEURONS_IN_IMAGE


def utc_today():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def spent_today():
    total = 0.0
    if RUNS.exists():
        for line in RUNS.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("utc_date") == utc_today() and r.get("status") == "ok":
                total += r.get("est_neurons", 0) or 0
    return total


def load_json(p, default):
    return json.loads(p.read_text()) if p.exists() else default


def ref_path(rid, idx):
    return REFS / f"{rid}_c{idx}.png"


def call_flux(model, prompt, w, h, seed, inputs):
    acct, token = os.environ["CLOUDFLARE_ACCOUNT_ID"], os.environ["CLOUDFLARE_API_TOKEN"]
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    # multipart is required by FLUX.2 even for prompt-only requests
    files = {"prompt": (None, prompt), "width": (None, str(w)), "height": (None, str(h)), "seed": (None, str(seed))}
    for i, b in enumerate(inputs):
        files[f"input_image_{i}"] = (f"ref{i}.png", b, "image/png")
    for attempt in range(1, 3):
        r = requests.post(url, headers={"Authorization": f"Bearer {token}"}, files=files, timeout=180)
        low = r.text.lower()
        if r.status_code == 429 or "daily free allocation" in low or "neurons" in low and r.status_code >= 400:
            raise QuotaStop(f"HTTP {r.status_code}: {r.text[:300]}")
        if r.status_code >= 500 and attempt == 1:
            time.sleep(5); continue
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:400]}")
        if r.headers.get("content-type", "").startswith("image/"):
            return r.content
        j = r.json()
        if not j.get("success", True):
            raise RuntimeError(f"API error: {j.get('errors')}")
        img = j["result"]["image"]
        return base64.b64decode(img.split(",", 1)[-1])
    raise RuntimeError("server error after retry")


def anchor_path(shot_id, selected):
    return KF / f"{shot_id}_c{selected.get(shot_id, 0)}.png"


def img_bytes(path, size):
    """PNG bytes shrunk below 512px (the API limit for input images)."""
    im = Image.open(path).convert("RGB")
    im.thumbnail((size - 64, size - 64))
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


def build_jobs(sb, args, selected):
    v = sb["visual"]; jobs = []
    ncand = args.candidates or v["candidates"]
    W, H = v["size"]["width"], v["size"]["height"]
    RS = v["reference_size"]
    anchors = v.get("anchors", {})
    anchor_ids = set(anchors.values())
    if args.refs:
        for n, (rid, r) in enumerate(v["references"].items()):
            for c in range(ncand):
                jobs.append(dict(label=f"{rid}_c{c}", path=ref_path(rid, c), prompt=r["prompt"], w=RS, h=RS,
                                 seed=v["base_seed"] + 100 * n + c,
                                 inputs=[("ref", x) for x in r.get("from", [])]))
        return jobs
    skipped = []
    shots = list(enumerate(sb["shots"]))
    shots.sort(key=lambda t: (t[1]["id"] not in anchor_ids, t[0]))      # anchor shots first
    for n, shot in shots:
        if args.shot and shot["id"] != args.shot:
            continue
        anchor = anchors.get(shot["scene"])
        use_anchor = anchor and anchor != shot["id"]
        if use_anchor and anchor not in selected:
            skipped.append((shot["id"], anchor)); continue
        rids = list(v["shot_refs"].get(shot["id"], []))
        rids = rids[: 4 - (1 if use_anchor else 0)]            # model accepts max 4 input images
        ins = [("ref", r) for r in rids] + ([("anchor", anchor)] if use_anchor else [])
        parts = []
        for i, (kind, ident) in enumerate(ins):
            if kind == "anchor":
                parts.append(f"image {i} is an approved frame of this same film: keep the same people, faces, hair, clothing and room")
            else:
                lock = v["references"][ident].get("lock", "")
                parts.append(f"image {i} shows {ident.replace('_', ' ')}" + (f" ({lock})" if lock else ""))
        intro = ("Reference images: " + "; ".join(parts) + ". Keep every person looking exactly like their reference. ") if ins else ""
        prompt = f"{intro}{v['style_blocks'][shot['scene']]} {shot['visual_prompt']} {v['common_suffix']}"
        for c in range(ncand):
            seed = v["base_seed"] + 1000 + c + (0 if v.get("same_seed", True) else 10 * (n + 1))
            jobs.append(dict(label=f"{shot['id']}_c{c}", path=KF / f"{shot['id']}_c{c}.png", prompt=prompt, w=W, h=H,
                             seed=seed, inputs=ins))
    for sid, a in skipped:
        print(f"  SKIPPED {sid}: first generate the anchor shot ({a}), look at it, then run --select {a} <number>")
    return jobs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refs", action="store_true"); ap.add_argument("--shot")
    ap.add_argument("--candidates", type=int); ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--select", nargs=2, metavar=("KEY", "INDEX"))
    args = ap.parse_args()
    load_env()
    sb = validate()
    if "visual" not in sb:
        sys.exit('storyboard.json has no "visual" block. Run: python pipeline/add_visual_block.py')
    v = sb["visual"]
    selected = load_json(SEL, {})

    if args.select:
        key, idx = args.select[0], int(args.select[1])
        f = ref_path(key, idx) if key in v["references"] else KF / f"{key}_c{idx}.png"
        if not f.exists():
            sys.exit(f"{f} does not exist yet.")
        selected[key] = idx
        SEL.parent.mkdir(parents=True, exist_ok=True); SEL.write_text(json.dumps(selected, indent=2))
        print(f"Selected {args.select[0]} -> candidate {args.select[1]}"); return

    jobs = build_jobs(sb, args, selected)
    manifest = load_json(MANIFEST, {})
    cap, done, cached, plan = v["daily_neuron_cap"], 0, 0, 0.0
    for j in jobs:
        j["n_in"] = len(j["inputs"])
        j["est"] = estimate(j["w"], j["h"], j["n_in"])

    def inputs_bytes(j):
        out = []
        for kind, ident in j["inputs"]:
            p = ref_path(ident, selected.get(ident, 0)) if kind == "ref" else anchor_path(ident, selected)
            if not p.exists():
                raise SystemExit(f"Missing {p.name}. Generate it first (see the workflow at the top of keyframes.py).")
            out.append(img_bytes(p, v["reference_size"]))
        return out

    if args.dry_run:
        todo = [j for j in jobs if args.force or not j["path"].exists()]
        print(f"{len(jobs)} images planned, {len(todo)} not yet generated.")
        print(f"Estimated cost of missing images: {sum(j['est'] for j in todo):.0f} neurons "
              f"(already spent today ~{spent_today():.0f}, cap {cap}).")
        return

    for k in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
        if not os.environ.get(k):
            sys.exit(f"Set {k} in .env")
    for d in (REFS, KF):
        d.mkdir(parents=True, exist_ok=True)

    try:
        for j in jobs:
            ins = inputs_bytes(j)
            h = hashlib.sha256(json.dumps([v["image_model"], j["prompt"], j["w"], j["h"], j["seed"],
                                           [hashlib.sha256(b).hexdigest() for b in ins]]).encode()).hexdigest()[:16]
            if not args.force and j["path"].exists() and manifest.get(j["label"]) == h:
                cached += 1; print(f"  cached  {j['label']}"); continue
            if spent_today() + j["est"] > cap:
                raise QuotaStop(f"Daily neuron cap {cap} reached (spent ~{spent_today():.0f}). Stopping before the call.")
            t = time.time()
            try:
                png = call_flux(v["image_model"], j["prompt"], j["w"], j["h"], j["seed"], ins)
                Image.open(io.BytesIO(png)).convert("RGB").save(j["path"], "PNG")
                manifest[j["label"]] = h
                MANIFEST.write_text(json.dumps(manifest, indent=2))
                log_run(stage="reference" if args.refs else "keyframes", key=j["label"], model=v["image_model"],
                        params={"w": j["w"], "h": j["h"], "inputs": [f"{k}:{i}" for k, i in j["inputs"]]}, seed=j["seed"],
                        est_neurons=round(j["est"], 1), utc_date=utc_today(),
                        latency_s=round(time.time() - t, 2), cost_usd=0.0, status="ok")
                done += 1; print(f"  made    {j['label']}  (~{j['est']:.0f} neurons)")
            except QuotaStop:
                raise
            except Exception as e:
                log_run(stage="keyframes", key=j["label"], model=v["image_model"], seed=j["seed"], utc_date=utc_today(),
                        latency_s=round(time.time() - t, 2), status="error", error=str(e)[:300])
                print(f"  FAILED  {j['label']}: {e}")
    except QuotaStop as e:
        log_run(stage="keyframes", key="quota", model=v["image_model"], utc_date=utc_today(), status="quota_stop", error=str(e)[:300])
        print(f"\nSTOPPED (quota): {e}\nCached images are kept. Re-run after 03:00 Addis Ababa time (00:00 UTC).")
    print(f"\nDone: {done} made, {cached} cached. Spent today (UTC) ~{spent_today():.0f} / {cap} neurons.")


if __name__ == "__main__":
    main()