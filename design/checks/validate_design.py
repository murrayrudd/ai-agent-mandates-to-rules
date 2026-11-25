"""Verify the design and specified examples. This script never contacts a model."""
import csv
import gzip
import itertools
import json
from collections import Counter,defaultdict
from decimal import Decimal as Dec
from pathlib import Path
from instrument import (B,D,DISC,LEVELS,PREMIUM,ROOT,Offer,digest,family_root,pair_id,
                        cost_crossing,parse,prescribed_step,qualification_messages,render,render_state,ruling,score,values)
from build_menus import (FAMILIES,FOCAL,NEUTRAL,dispatch_blocks,dispatch_slots,excluded_roots,paths,phase)


def readrows(p):
    fn = gzip.open if p.suffix == '.gz' else open
    with fn(p, 'rt', encoding='utf-8', newline='') as x:
        return list(csv.DictReader(x))


def independent_cash_states(o, k):
    s = Dec(0)
    prob_loss = Dec(o.bp) / 10000
    for delivered, pr_delivery in ((True, Dec('.99')), (False, Dec('.01'))):
        for lost, pr_risk in ((True, prob_loss), (False, 1 - prob_loss)):
            v = Dec(-100) - Dec(o.fee) / 10
            v += B if delivered else o.refund
            v -= 1000 if lost else 0
            v += k if o.keys == 'operator' else 0
            v -= DISC[o.identity]
            s += v * pr_delivery * pr_risk
    return s * 100


def static_arithmetic():
    n = 0
    for f, p, r, k, d in itertools.product(LEVELS['fee_tenths_c'], LEVELS['reserve_loss_bp'], LEVELS['refund_if_nondelivery_c'], LEVELS['key_authority'], LEVELS['disclosure']):
        o = Offer(f, p, r, k, d)
        o.validate()
        for premium in PREMIUM.values():
            assert independent_cash_states(o, premium) == score(o, premium)
        n += 1
    assert n == 486
    fix = json.loads((ROOT / 'checks/utility_fixtures.json').read_text())
    for z in fix:
        a, b = (Offer(*z['A']), Offer(*z['B']))
        for operator, k in PREMIUM.items():
            expected = z['expected_A_B_DECLINE_in_hundredths_of_cent'][operator]
            assert list(values(a, b, k).values()) == expected
            act = ruling(a, b, k)
            flip = ruling(b, a, k)
            assert ('B' if act == 'A' else 'A' if act == 'B' else act) == flip
            assert values(a, b, k)[act] == max(expected)
    assert cost_crossing(12, 0, 0, 12) == ('finite', 1)
    assert cost_crossing(6, 2, 6, 2) == ('coincident', None)
    assert cost_crossing(6, 2, 5, 2) == ('parallel', None)
    assert cost_crossing(4, 0, 6, 2) == ('outside', -1)
    return (n, len(fix))


def parsing_and_states():
    a = Offer(1, 1, 0, 'provider', 'transaction')
    b = Offer(51, 1, 0, 'operator', 'transaction')
    ctl = '{"provisional":"DECLINE","disposition":"REFER","issue":"CONTROL"}'
    other = ctl.replace('CONTROL', 'OTHER')
    act = '{"provisional":"A","disposition":"ACT","issue":"NONE"}'
    invalid = ['{}', act.replace('"NONE"', '"OTHER"'), act + ' prose', '[' + act + ']', act.replace('"A"', '"A","provisional":"B"'), act.replace('"A"', '"a"')]
    for bad in invalid:
        try: parse(bad,"referral")
        except ValueError: pass
        else: raise AssertionError(bad)
    assert prescribed_step(a, b, 2, 'STANDING', ctl)[0]['executed'] == 'NO_EXECUTION'
    assert prescribed_step(a, b, 2, 'SHARED', other) == [dict(next='SHARED', executed='A', reviews=1, new_rules=0)]
    assert prescribed_step(a, a, 2, 'SHARED', ctl)[0]['next'] == 'SHARED'
    assert prescribed_step(a, b, 2, 'SHARED', act) == [dict(next='SHARED', executed='A', reviews=0, new_rules=0)]
    for k, expected in [(2, 'A'), (10, 'B')]:
        one, reuse = prescribed_step(a, b, k, 'SHARED', ctl)
        assert [one['next'], reuse['next']] == ['CASE', 'RULE']
        assert one['executed'] == reuse['executed'] == expected
        assert one['reviews'] == reuse['reviews'] == 1
        assert one['new_rules'] == 0 and reuse['new_rules'] == 1
        assert prescribed_step(a, b, k, 'RULE', ctl) == [dict(next='RULE', executed=expected, reviews=1, new_rules=0)]
        assert prescribed_step(a, b, k, 'CASE', ctl) == [dict(next='CASE', executed=expected, reviews=1, new_rules=0)]
        assert prescribed_step(a, b, k, 'RULE', None) == [dict(next='RULE', executed='NO_EXECUTION', reviews=0, new_rules=0)]
        assert render(a, b, 2, 'referral') == render(a, b, 2, 'referral', None)
        pre = render(a, b, 2, 'referral')[1]['content']
        post = render(a, b, 3, 'referral', k)[1]['content']
        assert 'under this mandate, add' not in pre
        assert f'under this mandate, add {k} cents' in post
        assert all((s not in pre for s in ('P001', 'O1', 'O2', 'SHARED', 'recurrence=')))
    for st in ('STANDING', 'SHARED', 'CASE'):
        assert render_state(a, b, 3, st, 'O1') == render_state(a, b, 3, st, 'O2')
    for st in ('UPFRONT', 'RULE'):
        assert render_state(a, b, 3, st, 'O1') != render_state(a, b, 3, st, 'O2')
    qs = json.loads((ROOT / 'checks/qualification.json').read_text())
    assert len(qs) == 8 and len({z['id'] for z in qs}) == 8 and all((z['answer'] in z['options'] for z in qs))
    assert all((qualification_messages(z) == qualification_messages({**z, 'answer': 'unread key'}) for z in qs))


def boundary_fixtures():
    """Prescribed receipts expose end-of-horizon charges and the no-trigger projection."""
    provider = Offer(1, 1, 0, 'provider', 'transaction')
    operator = Offer(51, 1, 0, 'operator', 'transaction')
    act = json.dumps({'provisional': 'A', 'disposition': 'ACT', 'issue': 'NONE'})
    refer = json.dumps({'provisional': 'A', 'disposition': 'REFER', 'issue': 'CONTROL'})
    prefix = [prescribed_step(provider, operator, 10, 'SHARED', act)[0] for _ in range(11)]
    no_trigger = prefix + [prescribed_step(provider, operator, 10, 'SHARED', act)[0]]
    assert all((x['next'] == 'SHARED' for x in no_trigger))
    assert sum((x['reviews'] for x in no_trigger)) == 0
    at_close = prescribed_step(provider, operator, 10, 'SHARED', refer)
    for terminal in at_close:
        path = prefix + [terminal]
        assert len(path) == D['horizon'] and sum((x['reviews'] for x in path)) == 1
        assert sum((x['new_rules'] for x in path)) == int(terminal['next'] == 'RULE')
        assert terminal['executed'] == 'B'
    fresh = render_state(provider, operator, 1, 'SHARED', 'O2')
    assert 'under this mandate, add 10 cents' not in fresh[1]['content']


def audit_banks():
    exclusions = excluded_roots()
    allroots = {}
    stats = {}
    archived = json.loads((ROOT / 'spec/schedule_inventory.json').read_text())
    for phase_name, n in FAMILIES.items():
        sp, op = paths(phase_name)
        assert digest(sp.read_bytes()) == archived[phase_name]['sequence_sha256']
        assert digest(op.read_bytes()) == archived[phase_name]['offer_sha256']
        offers = {z['offer_id']: Offer(int(z['fee_tenths_c']), int(z['reserve_loss_bp']), int(z['refund_if_nondelivery_c']), z['keys'], z['identity']) for z in readrows(op)}
        for oid, o in offers.items():
            o.validate()
            assert oid == o.id()
        byfamily = defaultdict(lambda: {'low': {}, 'high': {}})
        allroots[phase_name] = set()
        rows = readrows(sp)
        assert len(rows) == 24 * n
        for row in rows:
            rec = row['recurrence']
            t = int(row['period'])
            points = byfamily[row['family']][rec]
            assert t not in points
            points[t] = row
            a, b = (offers[row['A']], offers[row['B']])
            root = family_root(a, b)
            assert root == row['economic_root'] and root not in exclusions and (phase(root) == phase_name)
            assert pair_id(a, b) == row['pair_id']
            allroots[phase_name].add(root)
        assert len(byfamily) == n
        for fid, series in byfamily.items():
            first = 2 if int(fid[1:]) % 2 == 1 else 3
            low, high = (series['low'], series['high'])
            assert set(low) == set(high) == set(range(1, 13))
            focal = [t for t in range(1, 13) if high[t]['role'] == 'custody']
            assert len(focal) == 6 and focal[0] == first
            assert [t for t in range(1, 13) if low[t]['role'] == 'custody'] == [first]
            assert {high[t]['cell'] for t in focal} == set(FOCAL)
            assert {high[t]['cell'] for t in high if t not in focal} == set(NEUTRAL)
            assert len({high[t]['economic_root'] for t in high}) == 12
            assert sum((offers[high[t]['A']].keys == 'operator' for t in focal)) == 3
            for t in range(1, 13):
                l, h = (low[t], high[t])
                assert l['economic_root'] == h['economic_root']
                same = all((l[v] == h[v] for v in ('A', 'B')))
                assert same == (t not in focal[1:])
                a, b = (offers[h['A']], offers[h['B']])
                for side in ('A', 'B'):
                    assert offers[l[side]].economics() == offers[h[side]].economics()
                if t in focal:
                    assert a.keys != b.keys
                if t in focal[1:]:
                    assert all((offers[l[s]].keys == 'provider' for s in ('A', 'B')))
                if h['cell'] in ('anchor', 'interior', 'transfer'):
                    assert ruling(a, b, 2) != ruling(a, b, 10)
                    assert 'DECLINE' not in (ruling(a, b, 2), ruling(a, b, 10))
                if h['cell'] == 'tie':
                    assert score(a, 2) == score(b, 2) > 0
                if h['cell'] == 'decline':
                    assert ruling(a, b, 2) == ruling(a, b, 10) == 'DECLINE'
        stats[phase_name] = {'families': n, 'rows': len(rows), 'unique_pairs': len({z['pair_id'] for z in rows})}
    for x, y in itertools.combinations(allroots, 2):
        assert allroots[x].isdisjoint(allroots[y])
    ss = dispatch_slots()
    given = readrows(ROOT / 'menus/pilot_dispatch.csv')
    assert [r['attempt_slot'] for r in given] == [r[0] for r in ss]
    assert len({r[0] for r in ss}) == len(ss) == 364
    assert sum((r[-1] != 'UPFRONT' for r in ss)) == 268
    assert len(dispatch_slots('precision', 16)) == 2144
    assert len(dispatch_slots('main', 24)) == 4368
    return stats


def audit_main_batches():
    full = list(dispatch_blocks('main', 128))
    assert [families for families, _ in full] == [range(1, 25), range(25, 49), range(49, 129)]
    complete_ids = set()
    for families, rows in full:
        assert {row[1] for row in rows} == {f'M{i:03}' for i in families}
        assert len(rows) == 182 * len(families)
        periods = [row[4] for row in rows]
        assert set(periods) == set(range(1, 13)) and periods == sorted(periods)
        ids = {row[0] for row in rows}
        assert len(ids) == len(rows) and not complete_ids.intersection(ids)
        complete_ids.update(ids)

    for target in (24, 28, 48, 52, 108, 128):
        plan = list(dispatch_blocks('main', target))
        assert plan[0] == full[0]
        if target >= 48:
            assert plan[:2] == full[:2]
        for index, (families, _) in enumerate(plan):
            completed = families.stop - 1
            resumed = list(dispatch_blocks('main', target, completed_through=completed))
            assert resumed == plan[index + 1:]
        assert {i for families, _ in plan for i in families} == set(range(1, target + 1))

    for invalid_boundary in (12, 25, 49):
        try:
            list(dispatch_blocks('main', 48, completed_through=invalid_boundary))
        except ValueError:
            continue
        raise AssertionError('An unverified partial block cannot be skipped')


def main():
    count, fix = static_arithmetic()
    parsing_and_states()
    boundary_fixtures()
    stats = audit_banks()
    audit_main_batches()
    print(f"PASS: {count} allowed offers × 2 profiles agree with an independent four-state cash ledger.")
    print(f"PASS: {fix} hand-specified utility fixtures, ties and mirrored choices.")
    print("PASS: response parsing, first eligible fork, single review charge, failure and clause scope.")
    print("PASS: matched monetary twins, private input isolation and disjoint phase allocations.")
    for stage, z in stats.items():
        print(f'{stage}: {z}')
    print("PASS: 268 core candidate purchase slots, 96 upfront slots, 8 separate qualification calls.")
    print("PASS: main batches end at families 24 and 48 or the frozen target. Resumed schedules exactly match the full schedule.")


if __name__ == '__main__':
    main()

