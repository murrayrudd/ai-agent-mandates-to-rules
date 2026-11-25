"""Replay the three completed experiments using their frozen menus and recorded first responses."""
import csv
import gzip
import json
import sys
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "design" / "checks"))
import instrument
from build_menus import dispatch_slots, paths

# The original prompt renderer reads the same frozen templates at each call.
instrument.textfile = lru_cache(maxsize=None)(instrument.textfile)


def rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf8", newline="") as stream:
        yield from csv.DictReader(stream)


def records(path):
    with gzip.open(path, "rt", encoding="utf8") as stream:
        for line in stream:
            yield json.loads(line)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_event(actual, menu, offers, stage, policy, operator, state, aid, fork, decision, outcome):
    a, b = offers[menu["A"]], offers[menu["B"]]
    values = instrument.values(a, b, instrument.PREMIUM[operator])
    maximum = max(values.values())
    executed = outcome["executed"]
    provisional = decision["provisional"] if decision is not None else None
    value = values.get(executed, 0)
    reviews = outcome["reviews"]
    trigger = aid is not None and aid == fork
    physical = {"A": a.id(), "B": b.id(), "DECLINE": "DECLINE", "NO_EXECUTION": "NO_EXECUTION"}
    expected = dict(
        stage=stage, family=menu["family"], recurrence=menu["recurrence"], period=int(menu["period"]),
        operator_code=operator, policy=policy, attempt_id=aid, fork_attempt_id=fork,
        pair_id=instrument.pair_id(a, b), offer_A=a.id(), offer_B=b.id(), executed_label=executed,
        executed_physical=physical[executed], operator_ruling=executed if reviews else None,
        qualified_first_referral=trigger, carry_rule_before=state in ("RULE", "UPFRONT"),
        carry_rule_after=policy == "UPFRONT" or (policy == "RULE" and (state == "RULE" or trigger)),
        review_count=reviews, later_clause_issued=outcome["new_rules"], provisional_label=provisional,
        best_physical_set=sorted(physical[key] for key, v in values.items() if v == maximum),
        provisional_value_100th_c=values.get(provisional), executed_value_100th_c=value,
        best_value_100th_c=maximum, loss_100th_c=maximum-value,
        immediate_recovered_100th_c=value-values[provisional] if reviews and decision else None,
        valid_first_attempt=None if aid is None else decision is not None,
    )
    if actual != expected:
        fields = [k for k in expected if actual.get(k) != expected[k]]
        raise ValueError(f"Event mismatch in {menu['family']}/{menu['period']}/{policy}: {fields}")


def replay(stage, folder, count):
    first = list(records(folder / "attempts.jsonl.gz"))
    attempts = {r["id"]: r for r in first}
    require(len(first) == len(attempts), f"{stage}: duplicate attempts")
    skipped = {r["id"] for r in rows(folder / "skipped_slots.csv")}
    events = {}
    for event in records(folder / "events.jsonl.gz"):
        key = tuple(event[k] for k in ("family", "recurrence", "period", "operator_code", "policy"))
        require(key not in events, f"Duplicate event {key}")
        events[key] = event
    event_count = len(events)
    menu_path, offer_path = paths(stage)
    offers = {r["offer_id"]: instrument.Offer(int(r["fee_tenths_c"]), int(r["reserve_loss_bp"]),
              int(r["refund_if_nondelivery_c"]), r["keys"], r["identity"]) for r in rows(offer_path)}
    menus = {(r["family"], r["recurrence"], int(r["period"])): r for r in rows(menu_path)
             if int(r["family"][1:]) <= count}
    tested = set()
    if stage == "pilot":
        qualification = json.loads((ROOT / "design/checks/qualification.json").read_text(encoding="utf8"))
        for item in qualification:
            aid = item["id"]
            r = attempts[aid]
            require(r["request"]["messages"] == instrument.qualification_messages(item), aid)
            require(r["status"] == "VALID" and json.loads(r["content"]) == r["decision"] == {"answer":item["answer"]}, aid)
            tested.add(aid)
    expected_skips = set()
    used = []
    for family, recurrence, period in sorted(menus):
        menu = menus[family, recurrence, period]
        a, b = offers[menu["A"]], offers[menu["B"]]
        for operator, premium in instrument.PREMIUM.items():
            prefix = (family, recurrence, period, operator)
            chosen = instrument.ruling(a, b, premium)
            outcome = {"executed": chosen, "reviews": 1, "new_rules": 0}
            check_event(events.pop((*prefix, "REVIEW_ALL")), menu, offers, stage, "REVIEW_ALL",
                        operator, "REVIEW_ALL", None, None, None, outcome)
    # Follow the actual conditional dispatch order; a fork at t affects slots only from t+1.
    forks = {}
    for aid, family, recurrence, operator, period, flag in dispatch_slots(stage, count):
        branch = (family, recurrence, operator)
        fork_period, fork = forks.get(branch, (0, None))
        if fork_period >= period or not flag.startswith("REF_"):
            fork = None
        if flag == "REF_RULE_IF_PRIOR_TRIGGER" and fork is None:
            expected_skips.add(aid)
            continue
        state = flag
        if flag == "REF_PRIMARY":
            state = "CASE" if fork is not None else "SHARED"
        elif flag == "REF_RULE_IF_PRIOR_TRIGGER":
            state = "RULE"
        menu = menus[family, recurrence, period]
        a, b = offers[menu["A"]], offers[menu["B"]]
        r = attempts[aid]
        require(r["state"] == state and r["period"] == period, f"Wrong state at {aid}")
        require(r["request"]["messages"] == instrument.render_state(a,b,period,state,operator), f"Prompt mismatch: {aid}")
        content = r["content"]
        decision = None
        if r["status"] == "VALID":
            authority = "standing" if state in ("STANDING", "UPFRONT") else "referral"
            decision = instrument.parse(content, authority)
        else:
            require(r["status"] == "TRANSPORT_ERROR" and content is None, f"Unknown failed response: {aid}")
        require(decision == r["decision"], f"Parsed decision mismatch: {aid}")
        outcomes = instrument.prescribed_step(a,b,instrument.PREMIUM[operator],state,content)
        policies = (state,)
        if state == "SHARED":
            policies = ("CASE", "RULE")
            if len(outcomes) == 2:
                fork = aid
                forks[branch] = (period, aid)
            else:
                outcomes *= 2
        for policy, outcome in zip(policies, outcomes, strict=True):
            k = (family, recurrence, period, operator, policy)
            check_event(events.pop(k), menu, offers, stage, policy, operator, state, aid, fork, decision, outcome)
        tested.add(aid)
        used.append(aid)
    require(not events and tested == attempts.keys() and expected_skips == skipped, f"{stage}: incomplete replay")
    require(used == [r["id"] for r in first if r["state"] != "QUAL"], f"{stage}: dispatch order mismatch")
    errors = sum(r["status"] != "VALID" for r in first)
    print(f"{stage}: {len(first):,} first attempts, {errors} failed, {len(skipped)} conditional skips, {event_count:,} verified outcomes.")


if __name__ == "__main__":
    replay("pilot", ROOT / "development/pilot", 2)
    replay("precision", ROOT / "development/calibration", 16)
    replay("main", ROOT / "data/main", 48)
