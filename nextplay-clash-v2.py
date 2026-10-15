import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

BATTLELOG = Path("battlelog.json")
HISTORY = Path("nextplay-clash-history.json")
OUTPUT = Path("nextplay-clash-review.json")

if not BATTLELOG.exists():
    raise SystemExit("battlelog.json not found")

fresh = json.loads(BATTLELOG.read_text())

if HISTORY.exists():
    history = json.loads(HISTORY.read_text())
else:
    history = []

def first(side):
    return side[0] if isinstance(side, list) and side else {}

def battle_key(b):
    you = first(b.get("team"))
    opp = first(b.get("opponent"))
    return "|".join([
        str(b.get("battleTime", "")),
        str(you.get("tag", "")),
        str(opp.get("tag", "")),
        str(you.get("crowns", "")),
        str(opp.get("crowns", "")),
    ])

existing = {battle_key(b): b for b in history}

for b in fresh:
    existing[battle_key(b)] = b

history = sorted(
    existing.values(),
    key=lambda b: b.get("battleTime", ""),
    reverse=True
)

HISTORY.write_text(json.dumps(history, indent=2))

def result(b):
    you = first(b.get("team"))
    opp = first(b.get("opponent"))

    yc = you.get("crowns")
    oc = opp.get("crowns")

    if not isinstance(yc, int) or not isinstance(oc, int):
        return "UNKNOWN"
    if yc > oc:
        return "WIN"
    if yc < oc:
        return "LOSS"
    return "DRAW"

def mode_name(b):
    return (
        (b.get("gameMode") or {}).get("name")
        or b.get("type")
        or "Unknown"
    )

def is_draft_mode(mode):
    s = mode.lower()
    return "draft" in s

def deck(player):
    return [c.get("name", "Unknown") for c in player.get("cards", [])]

def average(vals):
    return round(mean(vals), 2) if vals else None

records = []

for b in history:
    you = first(b.get("team"))
    opp = first(b.get("opponent"))

    r = result(b)
    mode = mode_name(b)

    yc = you.get("crowns")
    oc = opp.get("crowns")

    records.append({
        "time": b.get("battleTime"),
        "result": r,
        "mode": mode,
        "draft_mode": is_draft_mode(mode),
        "your_crowns": yc,
        "opponent_crowns": oc,
        "crown_diff": (
            yc - oc
            if isinstance(yc, int) and isinstance(oc, int)
            else None
        ),
        "opponent": opp.get("name"),
        "your_deck": deck(you),
        "opponent_deck": deck(opp),
        "your_elixir_leaked_raw": you.get("elixirLeaked"),
        "opponent_elixir_leaked_raw": opp.get("elixirLeaked"),
    })

wins = [r for r in records if r["result"] == "WIN"]
losses = [r for r in records if r["result"] == "LOSS"]
draws = [r for r in records if r["result"] == "DRAW"]

decided = len(wins) + len(losses)

mode_stats = defaultdict(lambda: {
    "games": 0,
    "wins": 0,
    "losses": 0,
    "draws": 0,
    "crown_diff": []
})

for r in records:
    m = mode_stats[r["mode"]]
    m["games"] += 1

    if r["result"] == "WIN":
        m["wins"] += 1
    elif r["result"] == "LOSS":
        m["losses"] += 1
    elif r["result"] == "DRAW":
        m["draws"] += 1

    if isinstance(r["crown_diff"], int):
        m["crown_diff"].append(r["crown_diff"])

for name, m in mode_stats.items():
    decided_mode = m["wins"] + m["losses"]

    m["win_rate"] = (
        round(m["wins"] / decided_mode * 100, 1)
        if decided_mode else None
    )

    m["avg_crown_diff"] = average(m["crown_diff"])
    del m["crown_diff"]

recent10 = records[:10]

recent_wins = sum(r["result"] == "WIN" for r in recent10)
recent_losses = sum(r["result"] == "LOSS" for r in recent10)

three_crown_wins = sum(
    r["result"] == "WIN" and r["your_crowns"] == 3
    for r in records
)

three_crown_losses = sum(
    r["result"] == "LOSS" and r["opponent_crowns"] == 3
    for r in records
)

raw_win_leak = [
    r["your_elixir_leaked_raw"]
    for r in records
    if r["result"] == "WIN"
    and isinstance(r["your_elixir_leaked_raw"], (int, float))
]

raw_loss_leak = [
    r["your_elixir_leaked_raw"]
    for r in records
    if r["result"] == "LOSS"
    and isinstance(r["your_elixir_leaked_raw"], (int, float))
]

draft_games = sum(r["draft_mode"] for r in records)

review = {
    "game": "clash_royale",
    "history_size": len(records),

    "overall": {
        "wins": len(wins),
        "losses": len(losses),
        "draws": len(draws),
        "win_rate": (
            round(len(wins) / decided * 100, 1)
            if decided else None
        ),
        "three_crown_wins": three_crown_wins,
        "three_crown_losses": three_crown_losses,
    },

    "recent_form": {
        "window": len(recent10),
        "wins": recent_wins,
        "losses": recent_losses,
    },

    "mode_stats": dict(mode_stats),

    "data_quality": {
        "draft_games": draft_games,
        "non_draft_games": len(records) - draft_games,
        "deck_coaching_confidence": (
            "LOW" if draft_games > len(records) / 2 else "MEDIUM"
        ),
        "reason": (
            "Most recorded games are draft modes, so fixed-deck "
            "card win rates should not be treated as reliable coaching."
            if draft_games > len(records) / 2
            else
            "Enough non-draft games exist for deck-level analysis."
        )
    },

    "elixir_leak_raw": {
        "avg_wins": average(raw_win_leak),
        "avg_losses": average(raw_loss_leak),
        "status": "UNVALIDATED",
        "coaching_allowed": False,
    },

    "nextplay": {
        "current_status": "API_ONLY",
        "can_prove": [
            "result",
            "crowns",
            "opponent",
            "battle mode",
            "cards/decks used",
            "recent form",
            "mode-specific performance",
        ],
        "cannot_prove_yet": [
            "exact card play order",
            "exact placement",
            "exact hand at a moment",
            "exact elixir at a moment",
            "specific timestamped mistakes",
            "missed defensive card",
            "overcommit at a specific push",
        ]
    },

    "battles": records
}

OUTPUT.write_text(json.dumps(review, indent=2))

print()
print("==========================================")
print("NEXTPLAY CLASH V2")
print("==========================================")
print(f"Stored battles:     {len(records)}")
print(f"Wins:               {len(wins)}")
print(f"Losses:             {len(losses)}")

if decided:
    print(f"Overall win rate:   {len(wins) / decided * 100:.1f}%")

print()
print("RECENT FORM")
print("------------------------------------------")
print(f"Last {len(recent10)}: {recent_wins}W - {recent_losses}L")

print()
print("GAME MODES")
print("------------------------------------------")

for name, stat in sorted(
    mode_stats.items(),
    key=lambda x: -x[1]["games"]
):
    print(
        f"{name:<36} "
        f"{stat['games']:>3} games   "
        f"{str(stat['win_rate']) + '%':>7}"
    )

print()
print("DATA QUALITY")
print("------------------------------------------")
print(f"Draft games:        {draft_games}")
print(f"Non-draft games:    {len(records) - draft_games}")
print(
    "Deck analysis:     "
    + review["data_quality"]["deck_coaching_confidence"]
    + " confidence"
)

print()
print("RAW ELIXIR FIELD")
print("------------------------------------------")
print(f"Win average:        {average(raw_win_leak)}")
print(f"Loss average:       {average(raw_loss_leak)}")
print("Coaching status:    DISABLED until validated")

print()
print("NEXTPLAY CURRENTLY KNOWS")
print("------------------------------------------")
for item in review["nextplay"]["can_prove"]:
    print(f"✓ {item}")

print()
print("NEXTPLAY DOES NOT YET KNOW")
print("------------------------------------------")
for item in review["nextplay"]["cannot_prove_yet"]:
    print(f"• {item}")

print()
print("Saved:")
print("  nextplay-clash-history.json")
print("  nextplay-clash-review.json")
print()
