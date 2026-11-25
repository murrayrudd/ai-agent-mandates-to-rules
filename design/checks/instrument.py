"""Paper 3 design arithmetic, rendering, and prescribed-response fixture checks. Offline."""
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
D = json.loads((ROOT / 'spec/design.json').read_text(encoding='utf-8'))
LEVELS = D['levels']
OPS = D['operators']
B = OPS['service_value_conditional_on_delivery_c']
PREMIUM = OPS['control_premium_c']
DISC = OPS['disclosure_costs_c']
DISPLAY = {'transaction': 'transaction pseudonym', 'persistent': 'persistent pseudonym', 'legal': 'verified legal identity'}


def jsonbytes(data):
    return json.dumps(data, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def digest(data):
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, order=True)
class Offer:
    fee: int
    bp: int
    refund: int
    keys: str
    identity: str

    def economics(self):
        return (self.fee, self.bp, self.refund, self.identity)

    def id(self):
        return f'f{self.fee:03}p{self.bp:03}r{self.refund:03}{self.keys[0]}{self.identity[0]}'

    def with_operator(self):
        return Offer(self.fee, self.bp, self.refund, 'operator', self.identity)

    def validate(self):
        values = [self.fee, self.bp, self.refund, self.keys, self.identity]
        for value, choices in zip(values, [LEVELS[t] for t in (
            "fee_tenths_c","reserve_loss_bp","refund_if_nondelivery_c","key_authority","disclosure")]):
            if value not in choices:
                raise ValueError(f'Unexpected offer level {value}')
        if 1000 + self.fee > 10 * D['purchase']['price_plus_fee_limit_c']:
            raise ValueError('Price and fee exceed cap')


def family_root(a, b):
    """Groups both orientations and the custody-matched counterfactual together."""
    return digest(jsonbytes(sorted([a.economics(), b.economics()])))


def pair_id(a, b):
    return '/'.join(sorted([a.id(), b.id()]))


def score(o, k, service_c=B):
    """Expected value in hundredths of a US cent, using integers throughout."""
    return (99*service_c - 10000 - 10*o.fee - 10*o.bp + o.refund
            + (100*k if o.keys == "operator" else 0) - 100*DISC[o.identity])


def values(a, b, k):
    return {'A': score(a, k), 'B': score(b, k), 'DECLINE': 0}


def ruling(a, b, k):
    u = values(a, b, k)
    best = max(u.values())
    if u['DECLINE'] == best:
        return 'DECLINE'
    return min((x for x in ('A', 'B') if u[x] == best), key=lambda x: {'A': a, 'B': b}[x].id())


def textfile(name):
    return (ROOT / 'prompts' / name).read_text(encoding='utf-8').strip()


def cost_crossing(k0, v0, k1, v1):
    """Crossing of two cost lines, using exact arithmetic on ledger fixtures."""
    if v1 == v0:
        return ('coincident' if k1 == k0 else 'parallel', None)
    cross = (Fraction(k0) - Fraction(k1)) / (Fraction(v1) - Fraction(v0))
    return ('outside' if cross < 0 else 'finite', cross)


def qualification_messages(item):
    question = item['question'] + '\n' + '\n'.join((k + '. ' + item['options'][k] for k in ('A', 'B', 'C')))
    material = '\n\n'.join((textfile('setting.txt'), textfile('mandate.txt'), textfile('qualification_context.txt'), question))
    return [{'role': 'system', 'content': textfile('qualification_system.txt')}, {'role': 'user', 'content': material}]


def offer_text(label, o):
    f = Decimal(o.fee) / 10
    risk = Decimal(o.bp) / 100
    return (f"Offer {label} | total fee {f:.1f} cents | reserve loss probability {risk:.2f}%"
            f" | purchase-price reimbursement after non-delivery {o.refund} cents"
            f" | {o.keys}-held reserve keys | {DISPLAY[o.identity]}"
            f" | price plus fee {100+f:.1f} cents | uncommitted cash at authorization {400-f:.1f} cents")


def render(a, b, period, authority, authorized_premium=None):
    if authority not in {'standing', 'referral'} or not 1 <= period <= D['horizon']:
        raise ValueError('Unknown public state')
    a.validate()
    b.validate()
    mandate = textfile('mandate.txt')
    if authorized_premium is not None:
        if authorized_premium not in PREMIUM.values():
            raise ValueError('Unknown authorized premium')
        mandate += '\n' + textfile('clause.txt').format(premium_c=authorized_premium)
    msg=textfile("user_template.txt").format(
        period=period,horizon=D["horizon"],setting=textfile("setting.txt"),
        effective_mandate=mandate,authority=textfile(authority+".txt"),
        offers=offer_text("A",a)+"\n"+offer_text("B",b))
    return [{'role': 'system', 'content': textfile('system.txt')}, {'role': 'user', 'content': msg}]


def render_state(a, b, period, state, operator_code):
    if state not in {'SHARED', 'CASE', 'RULE', 'STANDING', 'UPFRONT'}:
        raise ValueError('Unknown decision state')
    authority = 'standing' if state in {'STANDING', 'UPFRONT'} else 'referral'
    k = PREMIUM[operator_code] if state in {'RULE', 'UPFRONT'} else None
    return render(a, b, period, authority, k)


def unique_dict(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError('Duplicate response field')
        d[k] = v
    return d


def parse(raw, authority):
    """Strict response shape. Accept whitespace. Reject surrounding prose and fenced JSON."""
    if authority not in {'standing', 'referral'}:
        raise ValueError('Unknown authority')
    z = json.loads(raw, object_pairs_hook=unique_dict)
    if type(z) is not dict or set(z) != {'provisional', 'disposition', 'issue'}:
        raise ValueError('Wrong response fields')
    if not all((type(x) is str for x in z.values())) or z['provisional'] not in ('A', 'B', 'DECLINE'):
        raise ValueError('Invalid provisional action')
    allowed = [('ACT', 'NONE')]
    if authority == 'referral':
        allowed.extend([("REFER","CONTROL"),("REFER","OTHER")])
    if (z['disposition'], z['issue']) not in allowed:
        raise ValueError('Decision outside authority or invalid issue')
    return z


def prescribed_step(a, b, k, state, raw):
    """A single state-machine fixture, not a dispatcher. REAL choices are never generated."""
    if state not in {'STANDING', 'UPFRONT', 'SHARED', 'CASE', 'RULE'}:
        raise ValueError('Unknown state')
    authority = 'standing' if state in {'STANDING', 'UPFRONT'} else 'referral'
    try:
        decision = parse(raw, authority)
    except (ValueError,TypeError):
        return [{'next': state, 'executed': 'NO_EXECUTION', 'reviews': 0, 'new_rules': 0}]
    action = decision['provisional']
    if decision['disposition'] == 'ACT':
        return [{'next': state, 'executed': action, 'reviews': 0, 'new_rules': 0}]
    final = ruling(a, b, k)
    eligible = decision['issue'] == 'CONTROL' and a.keys != b.keys
    if state == 'SHARED' and eligible:
        return [{"next":"CASE","executed":final,"reviews":1,"new_rules":0},
                {"next":"RULE","executed":final,"reviews":1,"new_rules":1}]
    return [{'next': state, 'executed': final, 'reviews': 1, 'new_rules': 0}]

