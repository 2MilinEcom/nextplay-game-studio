# NextPlay Game Studio

I built Game Studio to review Clash Royale recordings alongside match data. I can upload a recording, inspect sampled observations, and turn a review into a small set of practice goals.

I kept the recording timeline and the official match record separate so the app does not treat a match result as proof of what happened on screen. I also included a local practice lab and screen coaching tools.

## Built with

I used Python and JavaScript, with FFmpeg for video processing and Swift helpers for local platform features.

## Inside the project

* `nextplay-studio/studio/`: the local server, review pipeline, and interface.
* `nextplay-studio/lab/`: practice tools.
* `nextplay-studio/live/`: screen coaching and replay tools.
* `nextplay-studio/tests/`: workflow checks.

## Running it

I follow the setup in `nextplay-studio/README.md` and install `nextplay-studio/requirements.txt` in a Python environment. Video processing requires FFmpeg. I configure my own API access when using model features.

I left personal recordings and player records out of this copy. The recognition model and compiled macOS player are separate dependencies; I kept the model source and license information in `nextplay-studio/models/units-manifest.json`.

## More detail

* [Local setup and feature details](nextplay-studio/README.md)
* [Practice lab](nextplay-studio/lab/README.md)
