"""Build stimulus schedules only. Seeded CPython 3.12 randomization, without agent calls."""
import csv
import gzip
import io
import itertools
import json
import random
from collections import defaultdict
from pathlib import Path
from instrument import (D, LEVELS, ROOT, Offer, digest, family_root, jsonbytes, pair_id, score)

FAMILIES = {'pilot': 2, 'precision': 16, 'main': 128}
SEQUENCE_FIELDS = ['family', 'recurrence', 'period', 'cell', 'role', 'pair_id', 'economic_root', 'A', 'B']
OFFER_FIELDS = ['offer_id', 'fee_tenths_c', 'reserve_loss_bp', 'refund_if_nondelivery_c', 'keys', 'identity']
FOCAL = ('anchor', 'below', 'interior', 'above', 'near', 'transfer')
NEUTRAL = ('decline', 'tie', 'risk', 'recovery', 'privacy', 'mixed')


def phase(ekey):
    n = int(digest((D['sampling']['partition_salt'] + '|' + ekey).encode())[:16], 16) % 100
    return 'pilot' if n < 20 else 'precision' if n < 45 else 'main'


def excluded_roots():
    prev = json.loads((ROOT / 'spec/paper2_exclusions.json').read_text())
    roots = set(prev['unique_excluded_economic_roots'])
    for item in json.loads((ROOT / 'checks/utility_fixtures.json').read_text()):
        roots.add(family_root(Offer(*item["A"]),Offer(*item["B"])))
    return roots


def candidate_pools():
    empty = excluded_roots()
    pools = defaultdict(lambda: defaultdict(list))
    lev = LEVELS
    offers=sorted(Offer(f,p,r,"provider",d) for f,p,r,d in itertools.product(
        lev["fee_tenths_c"],lev["reserve_loss_bp"],lev["refund_if_nondelivery_c"],lev["disclosure"]))
    for a, b in itertools.combinations(offers, 2):
        ekey = family_root(a, b)
        if ekey in empty:
            continue
        groups = []
        ua, ub = (score(a, 0), score(b, 0))
        changed = sum((a.bp != b.bp, a.refund != b.refund, a.identity != b.identity))
        premium = b.fee - a.fee
        if ua < 0 and ub < 0:
            groups.append("decline")
        if ua == ub and ua > 0:
            groups.append("tie")
        if ua != ub and max(ua, ub) > 0:
            if changed >= 2:
                groups.append("mixed")
            if premium > 0 and changed == 1:
                if b.bp < a.bp:
                    groups.append("risk")
                if b.refund > a.refund:
                    groups.append("recovery")
                if {'transaction': 0, 'persistent': 1, 'legal': 2}[b.identity] < {'transaction': 0, 'persistent': 1, 'legal': 2}[a.identity]:
                    groups.append("privacy")
        if ua > 0 and premium > 0:
            if changed == 0:
                if 25 <= premium <= 94:
                    groups.extend(["anchor","interior"])
                if premium < 15:
                    groups.append("below")
                if premium > 102:
                    groups.append("above")
                if premium in {18, 19, 20, 99, 100, 101}:
                    groups.append("near")
            elif changed==1 and ub+200 < ua < ub+1000:
                groups.append("transfer")
        if groups:
            record = (a, b, ekey)
            for grp in groups:
                pools[phase(ekey)][grp].append(record)
    return pools


def balanced_positions(first, rng):
    rest = list(range(first + 1, 13))
    parts = [rest[i * len(rest) // 5:(i + 1) * len(rest) // 5] for i in range(5)]
    return [first] + [rng.choice(x) for x in parts]


def choose(pool, rng, used, excluded_premium=None):
    # A random starting sample with rejection is uniform among the eligible records.
    for _ in range(1000):
        a, b, key = rng.choice(pool)
        if key not in used and b.fee - a.fee != excluded_premium:
            used.add(key)
            return (a, b, key)
    eligible = [r for r in pool if r[2] not in used and r[1].fee - r[0].fee != excluded_premium]
    if not eligible:
        raise ValueError('Design stratum exhausted')
    ans = rng.choice(eligible)
    used.add(ans[2])
    return ans


def generate(stage, idx, pools):
    fid = {'pilot': 'P', 'precision': 'D', 'main': 'M'}[stage] + f'{idx:03}'
    rng = random.Random(int(digest((D['sampling']['sequence_seed'] + '|' + fid).encode()), 16))
    first = 2 if idx % 2 else 3
    pos = balanced_positions(first, rng)
    after = list(FOCAL[1:])
    rng.shuffle(after)
    focal = {t: (k, n) for n, (t, k) in enumerate(zip(pos, ['anchor'] + after))}
    neutrals = list(NEUTRAL)
    rng.shuffle(neutrals)
    used = set()
    menus = {}
    lookup = {}
    anchor_premium = None
    for t in range(1, 13):
        if t in focal:
            cell, rank = focal[t]
            a, b, key = choose(pools[stage][cell], rng, used, anchor_premium if cell == 'interior' else None)
            if cell == 'anchor':
                anchor_premium = b.fee - a.fee
            # Keep the side of the candidate for operator custody fixed in the financial twin.
            reverse = (idx + rank) % 2 == 1
        else:
            cell = neutrals.pop()
            a, b, key = choose(pools[stage][cell], rng, used)
            reverse = bool(rng.getrandbits(1))
        for rec in ('low', 'high'):
            focal_here = t in focal and (rec == 'high' or t == first)
            partner = b.with_operator() if focal_here else b
            A, B = (partner, a) if reverse else (a, partner)
            lookup[A.id()] = A
            lookup[B.id()] = B
            role = 'custody' if focal_here else 'replacement_control' if t in focal else 'common_control'
            menus[rec, t] = [fid, rec, t, cell, role, pair_id(A, B), key, A.id(), B.id()]
    return ([menus[rec, t] for rec in ('low', 'high') for t in range(1, 13)], lookup)


def csv_bytes(fields, rows):
    s = io.StringIO(newline='')
    w = csv.writer(s, lineterminator='\n')
    w.writerow(fields)
    w.writerows(rows)
    return s.getvalue().encode('utf-8')


def save(p, body):
    p.parent.mkdir(exist_ok=True,parents=True)
    if p.suffix == '.gz':
        buf = io.BytesIO()
        with gzip.GzipFile(filename='', mode='wb', fileobj=buf, mtime=0) as stream:
            stream.write(body)
        p.write_bytes(buf.getvalue())
    else:
        p.write_bytes(body)


def paths(stage):
    if stage == 'pilot':
        return (ROOT / 'menus/pilot_sequences.csv', ROOT / 'menus/pilot_offers.csv')
    return (ROOT / f'reserved/{stage}_sequences.csv.gz', ROOT / f'reserved/{stage}_offers.csv.gz')


def dispatch_blocks(stage='pilot', family_count=None, *, completed_through=0):
    """Yield (family range, candidate slots) after the last completed block."""
    if stage not in FAMILIES:
        raise ValueError('Unknown stage')
    count = FAMILIES[stage] if family_count is None else family_count
    if not 1 <= count <= FAMILIES[stage]:
        raise ValueError('Outside reserved family count')
    pauses = D['collection']['main_batch_endpoints'] if stage == 'main' else []
    boundaries = [0, *(n for n in pauses if n < count), count]
    if completed_through not in boundaries:
        raise ValueError('Resume from a completed block boundary within the fixed sample')

    slots = ['STANDING', 'REF_PRIMARY', 'REF_RULE_IF_PRIOR_TRIGGER']
    if stage != 'precision':
        slots.append("UPFRONT")
    prefix = {'pilot': 'P', 'precision': 'D', 'main': 'M'}[stage]
    for previous, end in itertools.pairwise(boundaries):
        if end <= completed_through:
            continue
        families = range(previous + 1, end + 1)
        rows = []
        for period in range(1, D['horizon'] + 1):
            candidates = []
            for index, recurrence, operator, slot in itertools.product(families, ('low', 'high'), ('O1', 'O2'), slots):
                earliest_referral = 2 if index % 2 else 3
                if slot == 'REF_RULE_IF_PRIOR_TRIGGER' and period <= earliest_referral:
                    continue
                family = f'{prefix}{index:03}'
                slot_id = f'{family}-{recurrence}-{operator}-t{period:02}-{slot}'
                priority = digest(('P3-dispatch-v1|' + slot_id).encode())
                candidates.append((priority, [slot_id, family, recurrence, operator, period, slot]))
            rows.extend(row for _, row in sorted(candidates))
        yield families, rows


def dispatch_slots(stage='pilot', family_count=None):
    return [row for _, block in dispatch_blocks(stage, family_count) for row in block]


def build():
    pools = candidate_pools()
    stats = {}
    for stage, n in FAMILIES.items():
        rows = []
        offers = {}
        for i in range(1, n + 1):
            seq, q = generate(stage, i, pools)
            rows.extend(seq)
            offers.update(q)
        sp, op = paths(stage)
        save(sp,csv_bytes(SEQUENCE_FIELDS,rows))
        offer_rows = ([oid, o.fee, o.bp, o.refund, o.keys, o.identity] for oid, o in sorted(offers.items()))
        save(op,csv_bytes(OFFER_FIELDS,offer_rows))
        stats[stage]={"families":n,"sequence_rows":len(rows),"distinct_physical_pairs":len({r[5] for r in rows}),
                      "distinct_economic_roots":len({r[6] for r in rows}),"distinct_offer_profiles":len(offers),
                      "candidate_counts_by_cell":{g:len(pools[stage][g]) for g in FOCAL+NEUTRAL},
                      "sequence_sha256":digest(sp.read_bytes()),"offer_sha256":digest(op.read_bytes())}
    (ROOT/"spec/schedule_inventory.json").write_text(json.dumps(stats,indent=2)+"\n",encoding="utf-8")
    save(ROOT/"menus/pilot_dispatch.csv",csv_bytes(["priority","attempt_slot","family","recurrence","operator","period","slot"],([i]+r for i,r in enumerate(dispatch_slots(),1))))
    return stats


if __name__ == '__main__':
    for k, v in build().items():
        print(k,v["families"],v["sequence_rows"],v["distinct_physical_pairs"])

