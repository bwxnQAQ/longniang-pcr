"""战后角色奖励的整队试排。"""
from . import chars, strategy as st


def unit(book, owned, rates, name, role, attr):
    return st.Unit(name, role, attr, name=name, base=chars.base_of(name),
                   func=book.role_as(name), tags=book.tags(name), atk=book.atk(name),
                   aid=book.aid(name), hit=book.hit(name), pos=book.pos(name),
                   power=book.power(name, rates), heal=book.heal(name),
                   pvp=book.is_pvp(name), tough=book.tough(name),
                   tough_p=book.tough_vs(name, "phys"), tough_m=book.tough_vs(name, "magic"),
                   unlisted=name not in owned)


def compare(team, offers, pick, profile, targets):
    base = st.team_score(team, profile, targets=targets)
    rows = []
    for candidate in offers:
        gain, replaced = 0.0, None
        for i, member in enumerate(team):
            trial = team[:i] + [candidate] + team[i+1:]
            if st.has_dup(trial):
                continue
            delta = round(st.team_score(trial, profile, targets=targets) - base, 3)
            if delta > gain:
                gain, replaced = delta, member.name
        rows.append(dict(name=candidate.name, outside=candidate.unlisted, gain=gain, out=replaced))
    best = max(row["gain"] for row in rows)
    winners = [i for i, row in enumerate(rows) if row["gain"] == best]
    return dict(base=round(base, 3), rows=rows, best=winners, agrees=pick in winners)


def trial_recruit(book, owned, team, offers, pick, road_rates, boss_rates):
    """两个场景共同首选一人时才改选。"""
    if not owned or len(team) != 5 or len(offers) != 3 or not all(all(card) for card in [*team, *offers]):
        return pick, {}
    if len({chars.base_of(card[0]) for card in team}) != 5 or len({card[0] for card in offers}) != 3:
        return pick, {}
    results = {}
    for key, profile, targets, rates in (("road", "fast", "multi", road_rates),
                                         ("boss", "burst", "single", boss_rates)):
        lineup = [unit(book, owned, rates, *card) for card in team]
        candidates = [unit(book, owned, rates, *card) for card in offers]
        results[key] = compare(lineup, candidates, pick, profile, targets)
    winners = set(results["road"]["best"]) & set(results["boss"]["best"])
    if len(winners) == 1 and pick not in winners:
        return winners.pop(), results
    return pick, results
