# Report: At One Table, In Different Worlds

*Edit this in your own words and export to PDF or Word. Everything in [brackets] is yours to complete, and the facts below come from the logs, so keep them accurate.*

## 1. What I set out to make, and for whom
A 60-90 second Amharic short film for Ethiopian families, especially young adults who remember home as it was and relatives who now live apart. It starts with a funny, familiar memory (the call from the gym, the rush to clean, the shared tiri, the uncle's Wednesday complaint) and ends on the same table in the present, where everyone is together but looking at their own screens. The audience should smile at the start, recognise themselves, and finish with one question: are we spending time together, or just sharing the same space? It deliberately does not blame technology, work or marriage. The pipeline runs from one file, `storyboard.json`, to two videos (9:16 and 16:9), 86 seconds plus a 2.5-second AI end card.

## 2. What I learned from my audience
- **Test 1 (radio cut, narration only):** [FILL: who listened, how many, what they understood, what was memorable, what confused them].
- **Test 2 (near-final cut):** [FILL].
- **What changed because of it:** [FILL: be specific: a line, a shot length, an image]. One change driven by data rather than people: measured speech showed the planned 73s did not fit, so shots were lengthened to 86s (EXPERIMENTS E2).

## 3. The hardest problem and how I solved it
[Choose the one that was truly hardest for you and give its evidence.] My candidate: **running out of Gemini TTS quota on deadline day** (FAILURES #2). The first full run made 13 of 17 clips and then returned 429 on every call. I checked the pattern (a daily cap, not a per-minute limit), rejected switching providers because it would have cost hours, and switched to the flash-lite TTS model for the last three shots. The hash-based cache meant the 13 finished clips were never regenerated. I then built the same protection into the keyframe stage: it counts estimated neurons per UTC day and stops before a call that would pass the cap.

## 4. A suggested practice that helped, and one that did not
- **Helped:** measuring before building. Writing the radio cut first and logging the length of every spoken line showed that my storyboard was 13s too short before any image existed (E2). [FILL: the practice you want to credit, with your own evidence.]
- **Did not help / did not beat my instinct:** [FILL honestly, with evidence from E4-E6 or elsewhere. For example: "I expected sharing one seed across shots to make characters match; the comparison showed ..." or "I expected the anchor frame to help; it ..."].

## 5. Ceiling work
Instead of stopping at a single working Text-to-Speech endpoint, I benchmarked both the full and lite Amharic TTS models side-by-side to evaluate trade-offs in synthesis latency, audio naturalness, and compute footprint.

## 6. Ethics and labelling
All characters are fictional; no real face or voice is used and no voice is cloned (preset Gemini voices). The film carries a "Made with AI" end card, and I will switch on the platform's AI label when I post. Licences are listed in `ETHICS.md`. 

## 7. What I would build next
A version in Afaan Oromo or Tigrinya, a lyric-video version with an Amharic song.