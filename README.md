# At One Table, In Different Worlds (በአንድ ጠረጴዛ፣ በተለያዩ ዓለማት)

A 60–90 second Amharic short film about how family life changes as we grow up: the same table, the same food, a very different atmosphere. Narration in Amharic, English subtitles, an AI-generated score, made entirely by a code pipeline driven from one file, `storyboard.json`.

**Everything is AI-generated and labelled as such** (see the end card and `ETHICS.md`). All characters are fictional.

## Run it

```bash
git clone <this repo> && cd <repo>
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then add your keys (only needed to regenerate; see below)
make film
```

`make film` validates the storyboard, then runs narration -> keyframes -> assembly -> cost report. **Each stage skips work that is already cached**, and the generated audio and images are committed in `outputs/`, so a clean clone rebuilds the film with *no API keys and no API calls*, using FFmpeg only. Final files: `outputs/final/film_9x16.mp4`, `outputs/final/film_16x9.mp4` and English `.srt` files.

Requirements: Python 3.9+, FFmpeg (with `sidechaincompress` and `loudnorm`), a Gemini API key and a Cloudflare Workers AI token if you want to regenerate audio or images. Keys go in `.env` (never committed): `GEMINI_API_KEY`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`.

## Change one shot and regenerate only that shot

1. Edit a narration line or a `visual_prompt` in `storyboard.json`.
2. `python pipeline/narration.py` -> only changed lines are regenerated (cache key = hash of model, text, voice, style).
3. `python pipeline/keyframes.py --shot shot_06` -> only that shot's images; then `python pipeline/keyframes.py --select shot_06 <0|1>`.
4. `make assemble` -> only segments whose picture or length changed are re-rendered.

## Stages

| Stage | Script | Reads | Writes | Model / tool |
|---|---|---|---|---|
| Validate | `pipeline/validate_storyboard.py` | `storyboard.json`, `schema/` | (errors) | jsonschema |
| Narration | `pipeline/narration.py` | storyboard | `outputs/audio/*.wav` | Gemini TTS |
| Radio cut | `pipeline/radio_cut.py` | audio | `outputs/radio_cut/` | FFmpeg |
| Keyframes | `pipeline/keyframes.py` | storyboard `visual` | `outputs/references/`, `outputs/keyframes/` | FLUX.2 klein 4B (Cloudflare) |
| Music | `outputs/music/score.wav` | caption below | score | ACE-Step 1.5 (local) |
| Assembly | `pipeline/assemble.py` | all of the above, `subtitles_en.json` | `outputs/final/` | FFmpeg + Pillow |
| Costs | `pipeline/costs.py` | `runs.jsonl` | `COSTS.md` | - |

## Documents

`DESIGN.md` (audience, intent, the two user tests and what they changed) · `ARCHITECTURE.md` · `EXPERIMENTS.md` · `FAILURES.md` · `COSTS.md` · `ETHICS.md` · `REPORT.md`. Every model call is one line in `runs.jsonl`.

## Cost

$0. Free tiers only. Measured numbers are in `COSTS.md`.