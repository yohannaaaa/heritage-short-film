# ARCHITECTURE

## Principle

`storyboard.json` is the single contract. Every stage reads it, validates it against `schema/storyboard.schema.json`, and writes files to `outputs/`. Stages never call each other: they communicate only through the storyboard and files on disk, so any stage can be run, changed or replaced alone.

```
storyboard.json ──validate──┬─> narration.py ──> outputs/audio/*.wav ──┬─> radio_cut.py ──> radio_cut.mp4
 (+ schema/)                │                                         │
                            ├─> keyframes.py ──> outputs/references/  ├─> assemble.py ──> outputs/final/
                            │                    outputs/keyframes/   │      ▲   film_9x16.mp4, film_16x9.mp4
                            │                    outputs/selected.json│      │
                            └─────────────────────────────────────────┘   outputs/music/score.wav, subtitles_en.json
runs.jsonl  <── every model or FFmpeg call logs one line ──> costs.py ──> COSTS.md
```

## Stage contracts

| Stage | Input contract | Output contract | Cache key |
|---|---|---|---|
| validate | schema + storyboard; shot ids unique; durations sum to `total_duration_seconds`; every dialogue speaker has a voice | exit code 0/1 | - |
| narration | `audio` block, `narration_am`, `dialogue` | one WAV per line: `<shot>_n<i>.wav` (narration), `<shot>_d<i>.wav` (dialogue) | sha256(model, text, voice, style) in `outputs/audio/manifest.json` |
| keyframes | `visual` block: style per scene, character `lock` text, references, `shot_refs`, `anchors` | `outputs/references/<id>_c<n>.png`, `outputs/keyframes/<shot>_c<n>.png`, `outputs/selected.json` | sha256(model, prompt, size, seed, bytes of every input image) |
| assemble | audio, selected keyframes (or `outputs/clips/<shot>.mp4`), `subtitles_en.json`, score | segments, final MP4s, SRT | sha256(source bytes, size, frames, motion) per segment |

## Design decisions

- **Speech sets the timing.** Amharic speech is measured after TTS. `assemble.py` lengthens a shot when its audio would not fit, so picture follows the voice.
- **One audio file per line.** A re-take regenerates one WAV, not the whole narration.
- **Consistency by construction.** Each character has one fixed description (`lock`) reused verbatim in the reference prompt and every shot prompt; every shot also receives the reference images, plus an approved *anchor* frame of its scene as an extra input image; one seed is shared across shots.
- **Human selection step.** Two candidates per image are generated; `--select` records the chosen one in `outputs/selected.json` (committed), which keeps runs reproducible.
- **Subtitles without libass.** The available FFmpeg build had no `subtitles`/`drawtext` filters, so subtitles are rendered as PNGs with Pillow and overlaid; an SRT is written alongside.
- **Ken Burns by default.** Motion is a slow pan/zoom over each keyframe (FFmpeg `zoompan`). An animated clip placed in `outputs/clips/<shot>.mp4` replaces it automatically.

## Failure handling

- **Validation first:** every stage validates the storyboard before any call, so bad input fails in milliseconds, not after quota is spent.
- **Narration:** retries up to 4 times with growing waits on 429/5xx; a 400 caused by the style field retries without it; a failed line is logged (`status: error`) and the run continues, exiting non-zero at the end. Re-running regenerates only the missing lines.
- **Keyframes:** estimated neuron cost is added to a daily total (UTC day) in `runs.jsonl`, and the script stops *before* any call that would pass `daily_neuron_cap`. A quota reply (429 or a "daily free allocation" message) stops the run immediately instead of retrying. Cached images are kept.
- **Assembly:** missing audio, subtitles or pictures are reported up front; an FFmpeg failure prints its stderr tail and exits.
- **Secrets:** read from `.env` (git-ignored); only `.env.example` is committed.

## Logging

`runs.jsonl`: one JSON object per call with `ts`, `stage`, `key`, `model`, `params`, `seed`, `latency_s`, `cost_usd`, `status`, and where relevant `chars`, `audio_seconds`, `est_neurons`, `utc_date`, `error`.