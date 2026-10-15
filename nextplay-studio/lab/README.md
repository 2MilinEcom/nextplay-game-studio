# NextPlay replay lab

A durable offline foundation for learning your Miner–Wall Breakers deck. The goal is better human play through verified replay review. Supercell prohibits gameplay automation: https://supercell.com/en/safe-and-fair-play/ . This module has no phone input, live capture, automatic battle entry or account credentials.

## Working today

- Versioned observations, exact JSON hashes and SQLite session history.
- Explicit source labels; synthetic demonstrations cannot mix with real replay observations.
- Manual replay labels with reviewer identity. Labels compare card selection only, not correct placement or strategic quality.
- Conservative defensive candidate rules for Balloon, ground tanks and swarms. These are hypotheses, not validated optimal moves.
- Unknown own elixir, uncertainty, missing cards, unaffordable moves and stale observations withhold recommendations.
- Report observation age/delay; real readiness remains unvalidated even when fixture tests pass.

## Use

From the nextplay-studio directory:

```sh
python3 -m lab --db /tmp/nextplay-demo.sqlite3 import demo lab/demo.json
python3 -m lab --db /tmp/nextplay-demo.sqlite3 label demo 0 tesla --reviewer manual-review
python3 -m lab --db /tmp/nextplay-demo.sqlite3 report demo
python3 -m unittest discover -s tests -p test_lab.py
```

Use a new session ID for each import. demo.json is fabricated software-test input, never gameplay evidence. Real observations must be manually annotated from recordings, with source manual_replay and evidence_id identifying the actual recording/frame. Times are milliseconds on one replay timeline; available_ms is when that observation was available, never an invented capture measurement. Arena x/y are normalized with origin top-left. Regions are illustrative; tile calibration is not implemented. Confidence is supplied by the annotator and not calibrated model probability.

## Development sequence and measurable acceptance criteria

1. Collect user-played recordings and annotate visible hand, own displayed elixir, threats and chosen actions. Separate training and evaluation by complete match, not nearby frames. At least 20 full annotated matches across several matchups is an initial development target, not evidence of leaderboard readiness.
2. Build visual recognition offline. Measure card accuracy, elixir errors, missed threats and false positives on held-out matches. Retain ambiguous frames; do not manufacture enemy hand/elixir.
3. Evaluate defensive patterns against expert human labels, including abstention, placement and timing. Current engine measures only card agreement. Add tower-damage outcomes only when directly visible and attributable; correlations do not prove the move caused damage.
4. Benchmark capture and processing independently. Suggested engineering target: p95 state age below 250ms, over 99% visible-hand recognition, no app-scope violations in the test set. These are proposed thresholds, not current achievements or guarantees. Current review engine rejects states older than 500ms.
5. Deliver post-match drills, matchup notes and progress tracking. Observe improvement over a substantial match sample, separate game mode, card levels and balance version, and compare to the player's own baseline. Leaderboard success cannot be promised.

## Boundaries

Official API history supplies deck/outcome context; it does not supply troop placements, card order, exact hand, live elixir or timestamped mistakes. elixirLeaked is rejected. No arbitrary state fields are accepted. This initial version has no vision detector, automatic app verifier, real-time gameplay loop or tile map. The Clash-only observation rule must be enforced by any future capture integration before frames are stored or sent to AI; an app title alone cannot verify the phone's foreground app.

SQLite schema version 1 is explicit. Future incompatible schema changes require migrations and backups. Keep recordings and annotations local, export only intentionally, and retain no personal app screens. No new OpenAI key or paid model call is needed to run this lab.
