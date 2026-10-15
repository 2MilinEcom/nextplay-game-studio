"""Explicit input readiness; predictions alone never qualify as live state."""

def blockers(state):
    reasons=[]
    if state.get('app')!='clash_royale':reasons.append('Clash Royale is not verified')
    if state.get('phase')!='battle':reasons.append('Battle is not verified')
    if state.get('replay',True):reasons.append('Replay cannot drive phone input')
    age=state.get('age_ms')
    if type(age) not in (int,float) or not 0<=age<=500:reasons.append('Frame freshness is unverified or stale')
    for key in ['hand_verified','elixir_verified','ownership_verified','placement_calibrated','mirror_connected']:
        if state.get(key) is not True:reasons.append(key+' is missing')
    return reasons
