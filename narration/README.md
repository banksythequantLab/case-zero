# Narration for voice cloning

Eight plain-text files, one per video segment. No markdown, no stage directions,
no numerals a TTS engine can mispronounce — every figure is already written the
way it should be spoken ("Fourteen and a half million", "S-E-C", "one-point-one-
seven million").

| file | slot | target | words | wpm |
|---|---|---|---|---|
| `01_000-020.txt` | 0:00–0:20 cold open | 20s | 46 | 138 |
| `02_020-040.txt` | 0:20–0:40 setup | 20s | 48 | 144 |
| `03_040-115.txt` | 0:40–1:15 the ledger | 35s | 85 | 146 |
| `04_115-210.txt` | 1:15–2:10 let it run | 55s | 69 | 75 |
| `05_210-245.txt` | 2:10–2:45 the punchline | 35s | 70 | 120 |
| `06_245-310.txt` | 2:45–3:10 Google Cloud | 25s | 49 | 118 |
| `07_310-333.txt` | 3:10–3:33 scorecard | 23s | 49 | 128 |
| `08_333-400.txt` | 3:33–4:00 close | 27s | 62 | 138 |

`ALL.txt` is the same content in one file with timecodes, if your tool prefers a
single pass.

## Generate per segment, not as one block

Then you can check each clip against its target duration and regenerate just the
one that runs long. A single 4-minute render that comes back at 4:06 means
starting over.

**Segment 4 is deliberately sparse** — 75 wpm across 55 seconds. That is not an
error. Most of that slot is the board running in silence, which is what makes it
read as autonomous. Do not pad it.

**Segment 3 is the tightest at 146 wpm.** If your cloned voice runs slower than
the source, this is the one that will overrun. Trim "No model. No prompt. No
variance." to "No model, no variance" if you need three seconds back.

## After generating

Check total runtime before you cut. Hard cap is 4:00 and going over invalidates
the submission — only the first four minutes are judged, so an overrun silently
truncates your close, which is the strongest line in the script.
