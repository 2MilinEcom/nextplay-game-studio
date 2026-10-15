# Local practice player prototype

The implementation now includes a persistent local recognizer, Swift mirrored-
window capture and input bridge, cropped clock/elixir OCR, portrait crop search,
card-slot placement, a deck-specific baseline policy, dashboard start/stop, and
per-game logs. It is not yet validated to play a decent match.

Use Screen coach → Local player prototype in the NextPlay dashboard. Open a
Clash Royale practice battle in iPhone Mirroring first. Watch without tapping
runs shadow mode. Start practice controller enables bounded card placement.
Neither mode starts a match or navigates phone menus. Stop controller terminates
the worker and its native helper. Closing the dashboard also requests stop.

The helper requests no permissions automatically. Screen Recording and
Accessibility must already be granted. Input requires the iPhone Mirroring app
in the foreground, an unchanged window, calibrated crop, a current capture less
than 500ms old and current battle/card/elixir signatures. Lost signatures stop
processing. Unknown observations do not generate a speculative input.

The policy prioritizes Tesla against repeated enemy threat candidates, then
close defensive units, then Miner/Wall Breakers pressure at high visible elixir.
Ownership uses an EXPERIMENTAL red/blue badge-color heuristic. Positions are
normalized pixel regions, not validated arena tiles. This must be calibrated and
tested in practice before considering ranked play. Poison and The Log rules cover narrow cluster/swarm cases only. The policy does
not predict opponent hand or optimize trades.

The native bridge performs selection and placement together; successful posting
is logged as an input, NOT proof that the game deployed the card. The controller waits for both a hand identity change and resource decrease
before proceeding. Those changes support deployment inference but do not prove
exact placement. A failed confirmation stops further input.

The small learner compares high-elixir pressure thresholds 8 and 9. Only a clear
recognized match result updates its win/game counters. Unknown/disconnected
sessions never train. This is a contextual parameter experiment, not training a
full neural gameplay policy, and it does not guarantee improvement per game.

Main modules: controller.py, mirror_bridge.swift, policy.py, manager.py, games.py.
replay_player.py exercises cropped native OCR, hand/unit recognition and policy
against saved frames without any input calls. Test results are in validation/.

Observed live blockers on 2026-10-14: mirror reports iCloud Signed Out; the native
helper lacks Accessibility access. The prototype has not completed a live game.

Resource OCR is checked against three rows of magenta gauge pixels to reject
observed 6/9 glyph confusion. Unreadable text can use a conservative gauge lower
bound; it is explicitly labeled as such and is not an exact hidden-state claim.
