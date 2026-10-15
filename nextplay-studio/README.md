# NextPlay Studio

A local training room for the existing NextPlay Clash pipeline. It uses your existing
`OPENAI_API_KEY`; it does not provision or expose another key.

## Open

Visit **http://127.0.0.1:8777** while the local service is running, or double-click
`Open-NextPlay.command`. The installer registers a login service that starts the app
on your Mac. It uses your existing shell environment without copying your API key.

### Recording review

Upload MP4, MOV, M4V, WebM, or MKV gameplay through the dashboard. Alternatively,
place a completed recording in `~/nextplay-clash/recordings-inbox`. The dedicated
inbox is watched by default while the app runs. Existing files elsewhere on your
Mac are never scanned. Changing or re-exporting a file creates a new hash; identical
recordings point to their existing review rather than spending another model call.

You can optionally select a match from official history. This is an explicit contextual
link, not a claim that the app has automatically identified the recording's match.
Without selection, the recording stays unlinked.

The app samples the entire recording (default maximum 24 frames), identifies visible
objects/UI, then runs a separate vision check on proposed observations. Rejected
observations are withheld from coaching. The accepted observations produce at most
two future review/practice goals. Frame anchors are copied from the extraction
manifest, not invented by the model. Clicking an anchor seeks the recording.

Phone MOV/HEVC and other containers are converted to a local H.264 playback preview;
original uploads are retained. Audio stays local and is not sent to the model.

### Screen coach

Open your gameplay or mirrored phone window on the Mac. In the Screen coach tab,
press **Start screen coach** and select the window in the browser's system picker.
Only you can authorize that browser/OS screen-sharing permission. No microphone or
camera permission is requested.

The app collects JPEG samples every 5 seconds, then checks batches of 6. Analysis
is asynchronous and capture pauses while a batch is checked. This is periodic screen
analysis, not instantaneous tactical guidance, complete gameplay tracking, or an
always-on phone observer. Latency depends on the API. Screen sessions have a default
limit of 20 checks; they stop at that limit, when you press Stop, when sharing ends,
or after an abandoned browser session times out. No new screenshot requests occur
after sharing stops. A currently submitted API request may finish.

Saved screen-session screenshots and reports remain in the library. Full-screen
video is not recorded by this feature; upload your phone recording when you want
full-speed replay playback.

### Official match data

The existing API → `nextplay-clash-v2.py` → `nextplay-clash-ai.py` pipeline remains
available. Settings has a Refresh button and recurring API refresh every ten minutes while
this local app runs. Automatic refresh is on by default. The collector and deterministic
analyzer run first; the AI outcome review runs only if its source hash changed, so
unchanged results do not trigger another coaching call. Saved history is deduplicated by the existing
analyzer. Current snapshot dates are shown; historical data are never silently
represented as newly played games.

### Reports and control

Every review offers JSON/Markdown exports, original/preview playback, sampled frames,
observation references, data limits, notes, cancel, retry, and delete. Notes stay on
your Mac and are not sent to the AI. Deleting a review removes managed local copies,
evidence, notes, and reports; your original inbox file is preserved. Test clips are
explicitly marked as tests and excluded from the count of your video reviews.

## Evidence contract

- The official API establishes outcome/deck/mode facts. It does not reveal gameplay.
- The raw `elixirLeaked` field is excluded from every studio model input.
- Screenshots establish only visible states, subject to image-recognition uncertainty.
- A second AI checker reduces hallucinations; it is not independent ground truth.
- Sparse samples cannot prove card order, exact hidden state, missed defensive cards,
  overcommits, elixir trades, causes of tower loss, or exact action/mistake timestamps.
- Draft-mode associations never become card rankings or fixed-deck recommendations.
- Advice is a future practice goal or a question to investigate, not an asserted past
  misplay. Unreadable footage can yield no observations and no tactical advice.
- Video-relative sample time is distinct from the in-game timer and official battle time.

## Limits and privacy

Defaults: 512 MB per upload, 20-minute recordings, 24 sampled frames, 6 frames per
vision batch. These can be adjusted within bounded ranges. A default recording uses
up to 4 observation calls, 4 checking calls, and 1 coaching call; batches with no
observations skip the checker and videos with no accepted observations skip coaching.
A default live session uses at most 60 model operations (20 checks × 3 operations);
stopping sooner uses fewer. The SDK can retry a transient request once, so request
attempts can be up to twice those limits. Existing OpenAI API usage is billed to your account. Settings and reports
record model selection and returned token usage, not credentials.

Local originals and frame/report files live in `~/nextplay-clash/studio-data`, protected
by directory/file permissions. The web server binds only to `127.0.0.1`. It checks Host
and Origin, blocks cross-site requests, requires a local session for data, and requires
a separate session header for mutations. API keys never reach browser JavaScript.
Only sampled image content and selected facts are sent to OpenAI with `store=False`;
that flag does not override the provider's applicable processing/retention policies.
No screen content is submitted until you select a window and start sharing.

## Dependencies

Python 3.10+, the OpenAI Python package, and FFmpeg/FFprobe. This Mac already had all
of them. `requirements.txt` documents the Python dependency; there is no heavy frontend
build or separate database server. The default model is `gpt-4.1`; Settings permits
another model with image and strict structured-output support, if your existing key
can access it.

## Service management

The macOS login service is `com.nextplay.studio` and its plist is in your
`~/Library/LaunchAgents` directory. Logs go to `studio-data/logs`. To stop the service:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.nextplay.studio.plist
```

To start it again:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.nextplay.studio.plist
```

To run manually from the existing-key terminal:

```bash
~/nextplay-clash/nextplay-studio/start-nextplay-studio.sh
```

The service starts an interactive login shell solely to read your existing shell
configuration, where this Mac already exports the key. If that environment changes,
Connection check will show the key as unavailable rather than requesting a new key.

## Validation

Run `python3 -B -m unittest discover -s tests -v` from this folder. Automated checks
cover extraction, references, withholding claims, context isolation, deduplication,
cancellation, restart recovery, live limits, exports, notes, upload, byte ranges, and
local request protection. End-to-end live API checks use conspicuously labeled test
footage and never treat it as player performance. Real gameplay quality still depends
on readable footage; no actual user gameplay recording was supplied during setup.

API implementation references:
- https://developers.openai.com/api/docs/guides/images-vision
- https://developers.openai.com/api/docs/guides/structured-outputs


## Local recording processing

Local is the default. Recordings are decoded at 2 fps on this Mac, with Apple Vision OCR at 1 fps. A full timestamped OCR/pixel-change timeline is saved beside the frames as `local-timeline.ndjson`. Bookmarks cover the recording and highlight large visual changes; every decoded screenshot remains available in the review. No OpenAI model is constructed or called for local recording reviews. Official API refresh still fetches match data and runs deterministic facts, but skips OpenAI coaching. Paid screen sessions are blocked while local mode is selected. Cloud review is an explicit alternative in Settings.

Requires macOS and the existing Swift command-line toolchain; the built-in Apple Vision helper is compiled once and cached. No model downloads or additional Python packages. CPU, disk, and initial compiler time still apply. Cancellation stops decoder/recognizer subprocesses.

This is a local evidence scanner, not a trained Clash game-state recognizer. OCR (including high-confidence OCR) can misread digits. It does not infer troop identity, exact hand or elixir, placements, actions, causal mistakes, or optimal moves. Local timeline coverage is half-second samples, not every video frame. Only upload footage of Clash Royale; trim notifications and other apps first to respect the Clash-only scope.

### Installed card and unit recognition

Local reviews now run `studio/recognize.py` in the isolated `.vision-venv` environment. Card identification uses SIFT descriptors, a ratio test, unique feature correspondences, RANSAC geometric verification, and a margin over competing card identities. The bundled official icon library covers the current eight-card deck, including downloaded evolution/hero artwork; base-card matches do not prove evolution status or affordability. Ambiguous, empty, or unsupported slots remain unknown. Artwork checksums are verified before loading.

Arena detection uses the public `units_M_480x352.onnx` model from Pbatch/ClashRoyaleBuildABot. NextPlay contains its own recording-only preprocessing and tracking code; no third-party phone navigation or control code is loaded. The model runs on CPU with ONNX Runtime telemetry disabled, a 0.90 score threshold, and at least three sightings for a repeated candidate. Stationary tower centers are excluded after false positives were observed in evaluation. Tracks never establish ownership, deployments, kills, or optimal moves. Model classes omit newer units such as Berserker and Spirit Empress; unfamiliar animations can be confused with older classes. Predictions remain unverified regardless of score or track length.

`local-recognition.json` records every frame's hand matches, unknown slots, boxes, local clock/text cues, and unit track candidates. The exported report includes this timeline and bracketed visible slot changes. Annotated screenshot links show the original frame with labels and boxes; original screenshots are preserved. The dashboard displays coverage rather than calling it accuracy, and offers a deterministic replay-verification checklist instead of invented tactical coaching.

The first validation uses 40 manually inspected slots from ten screenshots in one recording, labeled by the agent before running that benchmark. All 36 visible cards matched and four empty slots remained unknown. This small check is not independent human validation and does not establish accuracy across other decks, phone layouts, arenas or recordings. Blank/gray controls, unsupported square layouts, and conservative track identity checks are included in `validation/check_recognition.py`. Run this with `.vision-venv/bin/python` and the original frame directory. Additional tests verify that unknown/missing frames do not become invented deployment events.

Dependencies in the tested local environment: NumPy 2.5.4, Pillow 12.3.0, OpenCV headless 5.0.0.93, ONNX Runtime 1.31.0, Python 3.12.14. The separate server continues to use its existing Python environment. Initial public asset downloads are a one-time setup; runtime processing does not download models or contact paid providers. Computation, electricity and storage still apply.

### Recognition sources and notices

- Card artwork: official `api-assets.clashroyale.com` URLs provided in saved official API card data. Supercell owns the game assets; this local personal coaching tool is unofficial.
- Detection model: https://github.com/Pbatch/ClashRoyaleBuildABot — model metadata declares AGPL-3.0; repository code is MIT. Source license is saved as `models/Pbatch-LICENSE.md`, and exact model SHA-256/source URL are recorded in `models/units-manifest.json`. Any redistribution must preserve applicable model/source terms. No gameplay-controller code from that repository is part of NextPlay.
- Feature matching reference: https://docs.opencv.org/4.x/dc/dc3/tutorial_py_matcher.html
- ONNX inference reference: https://onnxruntime.ai/docs/get-started/with-python.html

Local outcome review now runs automatically after recognition. It uses cropped,
upsized Apple Vision OCR for tower health on the supported portrait layout,
accepts only digit readings with confidence at least 0.9, and requires the same
value in two consecutive one-second samples. Only active gameplay candidates
are evaluated. Missing readings break confirmation, increases are not damage,
and gaps over four seconds or drops over 2500 HP are withheld. Each accepted
HP drop links four confirmation screenshots and an approximate replay interval.
The dashboard and JSON/Markdown exports label enemy damage favorable and own
damage unfavorable **as outcomes**, never as proof of a good/bad decision.
Spell value, defense quality, full-elixir waste and complete tower trades remain
ungraded because deployment, ownership and exact resources are not established.
No network call or cloud fallback is involved. Apple OCR and feature matching are
local computer vision; the existing troop detector uses a local trained model.
