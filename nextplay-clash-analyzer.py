import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

BATTLELOG = Path("battlelog.json")

if not BATTLELOG.exists():
    raise SystemExit("battlelog.json not found")

battles = json.loads(BATTLELOG.read_text())

def first_player(side):
    if isinstance(side, list) and side:
        return side[0]
    return {}

def result_for(battle):
    you = first_player(battle.get("team"))
    opp = first_player(battle.get("opponent"))

    yc = you.get("crowns")
    oc = opp.get("crowns")

    if yc is None or oc is None:
        return "UNKNOWN"

    if yc > oc:
        return "WIN"
    if yc < oc:
        return "LOSS"
    return "DRAW"

def deck_names(player):
    return [
        card.get("name", "Unknown")
        for card in player.get("cards", [])
    ]

def avg(values):
    return round(mean(values), 2) if values else None

wins = 0
losses = 0
draws = 0

win_leak = []
loss_leak = []
opp_win_leak = []
opp_loss_leak = []

card_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "games": 0})
opponent_card_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "games": 0})

normalized = []

for i, battle in enumerate(battles, 1):
    you = first_player(battle.get("team"))
    opp = first_player(battle.get("opponent"))

    result = result_for(battle)

    if result == "WIN":
        wins += 1
    elif result == "LOSS":
        losses += 1
    else:
        draws += 1

    your_leak = you.get("elixirLeaked")
    opp_leak = opp.get("elixirLeaked")

    if isinstance(your_leak, (int, float)):
        if result == "WIN":
            win_leak.append(your_leak)
        elif result == "LOSS":
            loss_leak.append(your_leak)

    if isinstance(opp_leak, (int, float)):
        if result == "WIN":
            opp_win_leak.append(opp_leak)
        elif result == "LOSS":
            opp_loss_leak.append(opp_leak)

    your_deck = deck_names(you)
    opp_deck = deck_names(opp)

    for card in your_deck:
        card_stats[card]["games"] += 1
        if result == "WIN":
            card_stats[card]["wins"] += 1
        elif result == "LOSS":
            card_stats[card]["losses"] += 1

    for card in opp_deck:
        opponent_card_stats[card]["games"] += 1
        if result == "WIN":
            opponent_card_stats[card]["wins"] += 1
        elif result == "LOSS":
            opponent_card_stats[card]["losses"] += 1

    normalized.append({
        "index": i,
        "battle_time": battle.get("battleTime"),
        "type": battle.get("type"),
        "game_mode": (battle.get("gameMode") or {}).get("name"),
        "result": result,
        "your_crowns": you.get("crowns"),
        "opponent_crowns": opp.get("crowns"),
        "opponent_name": opp.get("name"),
        "your_elixir_leaked_raw": your_leak,
        "opponent_elixir_leaked_raw": opp_leak,
        "your_deck": your_deck,
        "opponent_deck": opp_deck,
    })

total = wins + losses + draws
decided = wins + losses

summary = {
    "battles_analyzed": total,
    "wins": wins,
    "losses": losses,
    "draws_or_unknown": draws,
    "win_rate_decided_percent": (
        round(wins / decided * 100, 1)
        if decided else None
    ),

    "raw_elixir_leaked": {
        "average_in_wins": avg(win_leak),
        "average_in_losses": avg(loss_leak),
        "opponent_average_when_you_win": avg(opp_win_leak),
        "opponent_average_when_you_lose": avg(opp_loss_leak),
        "warning": (
            "Raw API field only. Do not turn this into coaching "
            "language until its scale/meaning is validated."
        )
    },

    "your_card_stats": {},
    "opponent_card_stats": {},
    "battles": normalized
}

for card, stat in sorted(
    card_stats.items(),
    key=lambda x: (-x[1]["games"], x[0])
):
    games = stat["games"]
    stat["win_rate"] = (
        round(stat["wins"] / games * 100, 1)
        if games else None
    )
    summary["your_card_stats"][card] = stat

for card, stat in sorted(
    opponent_card_stats.items(),
    key=lambda x: (-x[1]["games"], x[0])
):
    games = stat["games"]
    stat["your_win_rate_against"] = (
        round(stat["wins"] / games * 100, 1)
        if games else None
    )
    summary["opponent_card_stats"][card] = stat

Path("nextplay-clash-summary.json").write_text(
    json.dumps(summary, indent=2)
)

print()
print("==========================================")
print("NEXTPLAY CLASH ROYALE ANALYSIS")
print("==========================================")
print(f"Battles analyzed: {total}")
print(f"Wins:             {wins}")
print(f"Losses:           {losses}")
print(f"Draw/unknown:     {draws}")

if decided:
    print(f"Win rate:         {wins / decided * 100:.1f}%")

print()
print("RAW ELIXIR LEAK FIELD")
print("------------------------------------------")
print(f"Average in wins:   {avg(win_leak)}")
print(f"Average in losses: {avg(loss_leak)}")
print()
print("NOTE: We are NOT treating this as a final")
print("coaching metric until we validate the API scale.")

print()
print("MOST COMMON CARDS YOU USED")
print("------------------------------------------")

for card, stat in list(summary["your_card_stats"].items())[:15]:
    print(
        f"{card:<24} "
        f"{stat['games']:>2} games  "
        f"{stat['win_rate']:>5}% win"
    )

print()
print("CARDS YOU FACED MOST")
print("------------------------------------------")

for card, stat in list(summary["opponent_card_stats"].items())[:15]:
    print(
        f"{card:<24} "
        f"{stat['games']:>2} games  "
        f"{stat['your_win_rate_against']:>5}% your win rate"
    )

print()
print("LATEST 10 BATTLES")
print("------------------------------------------")

for battle in normalized[:10]:
    mode = battle["game_mode"] or battle["type"] or "Unknown"
    print(
        f"{battle['result']:<5} "
        f"{battle['your_crowns']}-{battle['opponent_crowns']}  "
        f"vs {battle['opponent_name']:<18} "
        f"{mode}"
    )

print()
print("Saved:")
print("  nextplay-clash-summary.json")
print()
