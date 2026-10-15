import json
import os
from pathlib import Path
from urllib.parse import quote

import requests

BASE_URL = "https://api.clashroyale.com/v1"

for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if not line or "=" not in line:
        continue
    key, value = line.split("=", 1)
    os.environ[key] = value

api_key = os.environ.get("CLASH_ROYALE_API_KEY", "").strip()
player_tag = os.environ.get("CLASH_ROYALE_PLAYER_TAG", "").strip()

if not api_key:
    raise SystemExit("Missing CLASH_ROYALE_API_KEY")

if not player_tag:
    raise SystemExit("Missing CLASH_ROYALE_PLAYER_TAG")

if not player_tag.startswith("#"):
    player_tag = "#" + player_tag

encoded_tag = quote(player_tag, safe="")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Accept": "application/json",
}

def get_json(path):
    try:
        response = requests.get(
            BASE_URL + path,
            headers=headers,
            timeout=20,
        )

        if response.status_code != 200:
            print(f"\nHTTP ERROR {response.status_code}")
            print(response.text)

            if response.status_code == 403:
                print(
                    "\nLikely cause: the IP address allowed on your "
                    "Clash Royale developer key does not match your "
                    "current public IP."
                )

            raise SystemExit(1)

        return response.json()

    except requests.exceptions.SSLError as exc:
        print("\nSSL ERROR")
        print(exc)
        raise SystemExit(1)

    except requests.exceptions.RequestException as exc:
        print("\nNETWORK ERROR")
        print(exc)
        raise SystemExit(1)


print("\nConnecting to Clash Royale API...")

profile = get_json(f"/players/{encoded_tag}")
battlelog = get_json(f"/players/{encoded_tag}/battlelog")

Path("player-profile.json").write_text(
    json.dumps(profile, indent=2),
    encoding="utf-8",
)

Path("battlelog.json").write_text(
    json.dumps(battlelog, indent=2),
    encoding="utf-8",
)

print("\n==========================================")
print("NEXTPLAY CLASH ROYALE CONNECTION")
print("==========================================")

print(f"Player:   {profile.get('name', 'Unknown')}")
print(f"Tag:      {profile.get('tag', player_tag)}")
print(f"Trophies: {profile.get('trophies', 'Unknown')}")
print(f"Battles:  {len(battlelog)} recent battles returned")

if battlelog:
    battle = battlelog[0]

    team = (battle.get("team") or [{}])[0]
    opponent = (battle.get("opponent") or [{}])[0]

    your_crowns = team.get("crowns")
    opponent_crowns = opponent.get("crowns")

    if your_crowns is not None and opponent_crowns is not None:
        if your_crowns > opponent_crowns:
            result = "WIN"
        elif your_crowns < opponent_crowns:
            result = "LOSS"
        else:
            result = "DRAW"
    else:
        result = "UNKNOWN"

    print("\nLATEST BATTLE")
    print("------------------------------------------")
    print(f"Result:   {result}")
    print(f"Time:     {battle.get('battleTime', 'Unknown')}")
    print(f"Type:     {battle.get('type', 'Unknown')}")
    print(f"Crowns:   {your_crowns} - {opponent_crowns}")
    print(f"Opponent: {opponent.get('name', 'Unknown')}")

    print("\nYour deck:")
    for card in team.get("cards") or []:
        print(f"  - {card.get('name', 'Unknown')}")

    print("\nOpponent deck:")
    for card in opponent.get("cards") or []:
        print(f"  - {card.get('name', 'Unknown')}")

    if "elixirLeaked" in team:
        print(f"\nYour leaked elixir:     {team.get('elixirLeaked')}")

    if "elixirLeaked" in opponent:
        print(f"Opponent leaked elixir: {opponent.get('elixirLeaked')}")

print("\nSaved:")
print("  player-profile.json")
print("  battlelog.json")
print("\nAPI connection successful.")
