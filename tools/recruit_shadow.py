"""离线回放战后招募。用上一场的五人队逐位试换，整份报告输出到标准输出。"""
import json
from collections import Counter
from pathlib import Path

from longniang_pcr import chars, damage, recruit, wiki


def main():
    root = Path.cwd()
    learned = root / "data/learned"
    book = chars.CharBook(learned / "portraits.json", chars.load_table(root / "data"))
    wiki.attach(book, learned)
    owned = book.owned()
    if not owned:
        raise SystemExit("缺少账号名单")
    road_rates = damage.DamageBook(learned / "damage.json").rates()
    boss_rates = damage.DamageBook(learned / "damage_boss.json").rates()
    skipped, cases = Counter(), []
    for log in sorted((root / "logs/runs").glob("*/events.jsonl")):
        plan, won = {}, False
        with log.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    e = json.loads(line)
                except ValueError:
                    plan, won = {}, False
                    continue
                kind = e.get("kind")
                if kind == "team_plan":
                    plan, won = e, False
                elif kind == "battle_end":
                    won = e.get("result") == "win" and e.get("team") == plan.get("names")
                elif kind == "recruit":
                    if not won:
                        skipped["no_matching_win"] += 1
                        continue
                    won = False
                    team, names = plan.get("names", []), e.get("names") or []
                    pairs = plan.get("team") or []
                    cards = e.get("resolved") or e.get("cards") or []
                    if len(team) != 5 or len(names) != 3 or not all(team + names):
                        skipped["unknown_name"] += 1
                        continue
                    if len(pairs) != 5 or len(cards) != 3 or not all(all(pair) for pair in pairs + cards):
                        skipped["unknown_card"] += 1
                        continue
                    case = dict(run=log.parent.name, t=e["t"], team=team, pick=e["pick"])
                    lineup = [(n, *p) for n, p in zip(team, pairs)]
                    offers = [(n, *p) for n, p in zip(names, cards)]
                    original = e.get("original_pick", e["pick"])
                    selected, scores = recruit.trial_recruit(book, owned, lineup, offers, original, road_rates, boss_rates)
                    case.update(original_pick=original, trial_pick=selected, **scores)
                    cases.append(case)
    print(json.dumps(dict(skipped=skipped, cases=cases)))


if __name__ == "__main__":
    main()
