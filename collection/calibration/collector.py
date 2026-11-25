"""Single-flight Paper 3 precision calibration. The credential is used only in HTTPS headers."""
import argparse
import csv
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
DESIGN = Path(os.environ.get('PAPER3_DESIGN', HERE / 'design'))
if not DESIGN.exists():
    DESIGN = HERE.parent / 'p3design' / 'paper3_design'
sys.path.insert(0, str(DESIGN / 'checks'))
import instrument as study

CONFIG = study.D['collection']
MODEL = CONFIG['request_model']
TARGET = CONFIG['target_model']
CAP = Decimal('5.37')
STAGE = 'precision'
FAMILIES = tuple(f'D{i:03d}' for i in range(1,17))
CORE = ('REVIEW_ALL','STANDING','CASE','RULE')
PER_PERIOD = len(FAMILIES)*len(study.PREMIUM)*2*len(CORE)
MAX_CALLS = json.loads((DESIGN/'spec/freeze.json').read_text())['calibration_purchase_slot_ceiling']
BASIS = HERE/'pilot_basis'
PILOT_BILL = Decimal(json.loads((BASIS/'final_billing.json').read_text())['sum_of_first_attempt_charges_usd'])
URL = 'https://openrouter.ai/api/v1'
ROUTE_URL = URL + '/models/' + MODEL + '/endpoints'
QUAL = json.loads((DESIGN/'checks/qualification.json').read_text(encoding='utf8'))
QUAL_KEYS = {q['id']:q['answer'] for q in QUAL}
OPTIONS = {
    'model': MODEL, 'stream': False,
    'max_tokens': CONFIG['max_output_tokens_including_reasoning'],
    'reasoning': {'effort': CONFIG['reasoning_effort']},
    'provider': {'only':['openai'], 'ignore':['openai/fast','openai/ultrafast'],
                 'allow_fallbacks':False, 'require_parameters':True,
                 'max_price':{'prompt':2,'completion':10}},
    'plugins': [{'id':p,'enabled':False} for p in ('web','response-healing','file-parser')],
    'transforms': [], 'usage': {'include':True}
}

class Pause(Exception):
    """Collection cannot safely dispatch the next first attempt."""

def now():
    return datetime.now(timezone.utc).isoformat()

def packed(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(',',':'),sort_keys=True).encode('utf8')

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def reserved_rows(name):
    with gzip.open(DESIGN/'reserved'/name,mode='rt',encoding='utf8',newline='') as stream:
        return list(csv.DictReader(stream))

from build_menus import dispatch_slots
SLOTS = [dict(zip(('attempt_slot','family','recurrence','operator','period','slot'),line,strict=True))
         for line in dispatch_slots(STAGE,len(FAMILIES))]
MENUS = {(r['family'],r['recurrence'],int(r['period'])):r for r in reserved_rows('precision_sequences.csv.gz')}
OFFERS = {r['offer_id']:study.Offer(int(r['fee_tenths_c']),int(r['reserve_loss_bp']),
          int(r['refund_if_nondelivery_c']),r['keys'],r['identity']) for r in reserved_rows('precision_offers.csv.gz')}
INPUT_HASH = sha(packed(OPTIONS))

@contextmanager
def exclusive(folder):
    from fcntl import LOCK_EX, LOCK_NB, flock
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'collector.lock').open('a+b') as lock:
        try:
            flock(lock,LOCK_EX|LOCK_NB)
        except BlockingIOError as exc:
            raise Pause('A collector is active for this journal.') from exc
        yield

def opened(folder):
    db=sqlite3.connect(folder/'journal.sqlite')
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA synchronous=FULL')
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript("""
    CREATE TABLE IF NOT EXISTS meta (id TEXT PRIMARY KEY, body BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS preflight (observed_at TEXT PRIMARY KEY, body BLOB NOT NULL);
    CREATE TABLE IF NOT EXISTS attempt (id TEXT PRIMARY KEY, period INTEGER NOT NULL,
      state TEXT NOT NULL, start TEXT NOT NULL, req BLOB NOT NULL, reserve TEXT NOT NULL,
      http INTEGER, raw BLOB, received TEXT, provider_id TEXT UNIQUE, cost TEXT, result BLOB);
    CREATE TABLE IF NOT EXISTS event (family TEXT, recurrence TEXT, operator TEXT, period INTEGER,
      policy TEXT, body BLOB NOT NULL, PRIMARY KEY(family,recurrence,operator,period,policy));
    CREATE TABLE IF NOT EXISTS skipped (id TEXT PRIMARY KEY, reason TEXT NOT NULL);
    """)
    return db

def manifest(db, mode):
    checksums=(DESIGN/'SHA256SUMS.txt').read_bytes()
    for line in checksums.decode().splitlines():
        digest,name=line.split('  ',1)
        if sha((DESIGN/name).read_bytes()) != digest:
            raise Pause('Design checksum changed for '+name)
    q=json.loads((BASIS/'qualification.json').read_text())
    prior=json.loads((BASIS/'manifest.json').read_text())
    closing=json.loads((BASIS/'final_billing.json').read_text())
    if (len(q)!=8 or {r['id'] for r in q}!=set(QUAL_KEYS) or
        not all(r['correct'] and r['received_answer']==QUAL_KEYS[r['id']] for r in q)
        or not closing['reconciled'] or prior['configuration']!=OPTIONS
        or prior['design_checksum_file_sha256']!=sha(checksums)):
        raise Pause('Earlier qualification or instrument does not match the calibration.')
    if (len(SLOTS)!=MAX_CALLS or {s['family'] for s in SLOTS}!=set(FAMILIES)
        or {s['slot'] for s in SLOTS}!={'STANDING','REF_PRIMARY','REF_RULE_IF_PRIOR_TRIGGER'}):
        raise Pause('Precision schedule does not match the reserved core design.')
    args={'study':'Agents CE Paper 3','stage':STAGE,'release':study.D['version'],'mode':mode,
          'families':FAMILIES,'core_policies':CORE,'design_checksum_file_sha256':sha(checksums),
          'qualification_sha256':sha((BASIS/'qualification.json').read_bytes()),
          'independent_pilot_spending_usd':str(PILOT_BILL),'configuration':OPTIONS,
          'target_endpoint':CONFIG['openrouter_endpoint_name'],'stage_ceiling_usd':str(CAP),
          'max_first_attempts':MAX_CALLS,'upfront':False,'max_concurrent_purchases':1,
          'schedule_sha256':sha(packed(SLOTS)),
          'response_format':'Free JSON according to the frozen public instructions and the frozen parser.',
          'implementation_sha256':sha(Path(__file__).read_bytes())}
    raw=packed(args)
    with db:
        prior=db.execute("SELECT body FROM meta WHERE id='manifest'").fetchone()
        if prior is None:
            db.execute("INSERT INTO meta VALUES ('manifest',?)",(raw,))
        elif prior[0]!=raw:
            raise Pause('The frozen run manifest differs from this configuration or implementation.')

def spent(db):
    return sum((Decimal(row[0]) for row in db.execute('SELECT cost FROM attempt WHERE cost IS NOT NULL')),Decimal(0))

def remaining_key(pre):
    return Decimal(str(pre['key']['limit_remaining']))

class LiveProvider:
    mode='live'
    def __init__(self):
        import httpx
        import urllib.request
        key=os.environ.get('OPENROUTER_API_KEY')
        if not key:
            key=(Path.home()/'.config/agents-ce-paper3/pilot-inference.key').read_text().strip()
        # Reuse one TLS connection over the environment's configured HTTPS route.
        proxy=urllib.request.getproxies().get('https')
        if urllib.request.proxy_bypass('openrouter.ai'):
            proxy=None
        self.client=httpx.Client(proxy=proxy,timeout=httpx.Timeout(150,connect=25),
                               limits=httpx.Limits(max_connections=1,max_keepalive_connections=1,keepalive_expiry=90),
                               follow_redirects=False)
        self.auth={'Authorization':'Bearer '+key}
    def read(self,url,headers):
        import httpx
        for i in range(4):
            try:
                resp=self.client.get(url,headers=headers,timeout=30)
                resp.raise_for_status()
                return json.loads(resp.content,parse_float=str)
            except (httpx.TransportError,httpx.HTTPStatusError) as exc:
                if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code not in (408,429,500,502,503,504):
                    raise
                if i==3: raise
                time.sleep(2**i)
    def credit_balance(self):
        credits=self.read(URL+'/credits',self.auth)['data']
        return Decimal(str(credits['total_credits']))-Decimal(str(credits['total_usage']))
    def key_state(self):
        d=self.read(URL+'/key',self.auth)['data']
        return {k:d.get(k) for k in ('limit','limit_remaining','usage','limit_reset','expires_at')}
    def preflight(self):
        data=self.read(ROUTE_URL,{})['data']
        found=[e for e in data['endpoints'] if e.get('tag')=='openai']
        if data['id']!=MODEL or len(found)!=1:
            raise Pause('The requested model and single standard endpoint could not be verified.')
        route=found[0]
        if (route.get('name')!=CONFIG['openrouter_endpoint_name'] or route.get('provider_name')!='OpenAI'
                or route.get('service_tier') is not None or route.get('status')!=0
                or not {'reasoning','max_tokens'}.issubset(route['supported_parameters'])):
            raise Pause('The dated standard OpenAI endpoint or necessary settings changed.')
        other=[e['tag'] for e in data['endpoints'] if e.get('tag','').startswith('openai/')
               and e['tag'] not in OPTIONS['provider']['ignore']]
        if other:
            raise Pause('Another eligible OpenAI endpoint is present. Verify routing alignment.')
        pr=route['pricing']
        if (Decimal(pr['prompt'])!=Decimal('.000002') or Decimal(pr['completion'])!=Decimal('.00001')
                or Decimal(pr.get('request','0') or '0')!=0):
            raise Pause('The quoted endpoint prices have changed.')
        key=self.key_state()
        if key['limit'] is None or key['limit_remaining'] is None or key['limit_reset'] is not None:
            raise Pause('The dedicated project key no longer has the expected nonresetting funding arrangement.')
        return {'route':route,'url':ROUTE_URL,'key':key,'account_available_usd':str(self.credit_balance()),
                'observed_utc':now()}
    def post(self,body):
        response=self.client.post(URL+'/chat/completions',content=body,
                                  headers={**self.auth,'Content-Type':'application/json'})
        return response.status_code,response.content
    def close(self):
        self.client.close()

def load_meta(db,name):
    row=db.execute('SELECT body FROM meta WHERE id=?',(name,)).fetchone()
    return json.loads(row[0]) if row else None

def settle_transport(db,provider,row):
    """Reconcile a missing receipt on the isolated key, with no second model call."""
    if row['cost'] is not None:
        return
    if db.execute('SELECT COUNT(*) FROM attempt WHERE cost IS NULL').fetchone()[0]!=1:
        raise Pause('More than one charge is outstanding. Reconcile before continuing.')
    rec=json.loads(row['result']) if row['result'] else {}
    if (row['provider_id'] or rec.get('provider_request_id')) and rec.get('charge') is None:
        from urllib.parse import urlencode
        rid=row['provider_id'] or rec['provider_request_id']
        gen=provider.read(URL+'/generation?'+urlencode({'id':rid}),provider.auth)['data']
        if gen.get('id')!=rid or gen.get('provider_name')!='OpenAI' or gen.get('model') not in (MODEL,TARGET):
            raise Pause('Generation metadata cannot corroborate the original receipt.')
        raw_cost=gen.get('total_cost')
        if raw_cost is None: raise Pause('Generation has no confirmed charge.')
        charge=Decimal(str(raw_cost))
        if not charge.is_finite() or not 0<=charge<=Decimal(row['reserve']):
            raise Pause('Unexpected provider charge.')
        evidence={'method':'generation metadata','charge':str(charge),'generation_id':rid,'utc':now()}
    else:
        if row['http'] not in (0,408,429,500,502,503,504,None):
            raise Pause(f"Administrative HTTP {row['http']} for {row['id']}. The assignment is pending review.")
        origin=load_meta(db,'opening_funding')
        confirmed=Decimal(origin['key_usage_usd'])+spent(db)
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['received'] or row['start'])).total_seconds()
        minimum=90 if row['received'] else 210
        while age<minimum:
            time.sleep(min(30,minimum-age))
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(row['received'] or row['start'])).total_seconds()
        samples=[]
        for _ in range(5):
            state=provider.key_state()
            samples.append({'utc':now(),'usage_usd':str(state['usage'])})
            if len(samples)>=2 and all(Decimal(m['usage_usd'])==confirmed for m in samples[-2:]):
                break
            time.sleep(35)
        else:
            raise Pause('Dedicated key meter does not reconcile with the other charges. Preserve the first attempt.')
        charge=Decimal(0)
        evidence={'method':'two settled dedicated-key meter readings with one outstanding attempt',
                  'expected_key_usage_usd':str(confirmed),'charge':'0','samples':samples}
    raw=row['raw'] or packed({'transport_exception':'ProcessInterrupted','description':'No receipt saved before interruption.'})
    if not rec:
        rec=parse_receipt(row['http'] or 0,raw,row['state'])
    rec['charge']=str(charge); rec['charge_source']=evidence['method']
    evidence['original_response_or_error_sha256']=sha(raw)
    with db:
        db.execute('INSERT INTO meta VALUES (?,?)',('reconciliation_'+row['id'],packed(evidence)))
        db.execute('UPDATE attempt SET raw=?,http=?,received=?,cost=?,result=? WHERE id=? AND cost IS NULL',
                   (raw,row['http'] or 0,row['received'] or now(),str(charge),packed(rec),row['id']))
    print('Reconciled '+row['id']+' at USD '+str(charge)+'. Original first attempt retained.',flush=True)

def start(db,provider):
    manifest(db,provider.mode)
    pre=provider.preflight()
    with db:
        db.execute('INSERT INTO preflight VALUES (?,?)',(pre['observed_utc'],packed(pre)))
        if load_meta(db,'opening_funding') is None:
            if Decimal(str(pre['key']['usage']))!=PILOT_BILL:
                raise Pause('The initial dedicated key meter does not agree with the closed pilot.')
            opening={'utc':pre['observed_utc'],'key_usage_usd':str(pre['key']['usage']),
                     'available_account_credit_usd':pre['account_available_usd'],
                     'stage_limit_usd':str(min(CAP,Decimal(pre['account_available_usd'])))}
            db.execute("INSERT INTO meta VALUES ('opening_funding',?)",(packed(opening),))
    for record in db.execute('SELECT * FROM attempt WHERE raw IS NOT NULL AND result IS NULL').fetchall():
        r=parse_receipt(record['http'],record['raw'],record['state'])
        with db:
            db.execute('UPDATE attempt SET provider_id=?,cost=?,result=? WHERE id=?',
                       (r['provider_request_id'],r['charge'],packed(r),record['id']))
    for row in db.execute('SELECT * FROM attempt WHERE cost IS NULL').fetchall():
        settle_transport(db,provider,row)
    return pre,spent(db)

def reserve_for(body,route):
    p=route['pricing']
    byte_bound=len(body)+256
    boundaries=[v['min_prompt_tokens'] for v in p.get('overrides',[]) if 'min_prompt_tokens' in v]
    if boundaries and byte_bound>=min(boundaries):
        raise Pause('Request exceeds the verified short-input price tier.')
    prompt_price=max(Decimal(p.get(k) or '0') for k in ('prompt','input_cache_write','input_cache_read'))
    return byte_bound*prompt_price+OPTIONS['max_tokens']*Decimal(p['completion'])

def parse_receipt(status,raw,stage_state):
    try:
        r=json.loads(raw,parse_float=str)
    except (ValueError,TypeError):
        r={}
    if not isinstance(r,dict):
        r={}
    u=r.get('usage') or {}
    if not isinstance(u,dict):
        u={}
    value=u.get('cost')
    charge=Decimal(str(value)) if value is not None else None
    if charge is not None and (not charge.is_finite() or charge<0):
        charge=None
    out={'status':'TRANSPORT_ERROR','decision':None,'content':None,'model':r.get('model'),
         'upstream':r.get('provider'),'provider_request_id':r.get('id'),'fingerprint':r.get('system_fingerprint'),
         'in_tokens':u.get('prompt_tokens'),'out_tokens':u.get('completion_tokens'),
         'reasoning_tokens':(u.get('completion_tokens_details') or {}).get('reasoning_tokens'),
         'cached_in_tokens':(u.get('prompt_tokens_details') or {}).get('cached_tokens'),'charge':str(charge) if charge is not None else None}
    if status!=200 or r.get('error') or not r.get('choices'):
        return out
    if r.get('provider')!='OpenAI' or r.get('model') not in (MODEL,TARGET) or not r.get('id'):
        out['status']='ROUTE_ERROR'
        return out
    choice=r['choices'][0]
    msg=choice.get('message') or {}
    out['content']=msg.get('content')
    out['status']='FORMAT_ERROR'
    if choice.get('finish_reason')!='stop' or msg.get('refusal') or not isinstance(out['content'],str):
        return out
    try:
        if stage_state=='QUAL':
            val=json.loads(out['content'],object_pairs_hook=study.unique_dict)
            if not isinstance(val,dict) or set(val)!={'answer'} or val['answer'] not in ('A','B','C'):
                return out
        elif stage_state in ('UPFRONT','STANDING'):
            val=study.parse(out['content'],'referral')
            if val['disposition']!='ACT':
                out['status']='AUTHORITY_ERROR'
                return out
        else:
            val=study.parse(out['content'],'referral')
    except (ValueError,TypeError):
        return out
    out.update(status='VALID',decision=val)
    return out

def submit(db,provider,session,aid,period,state,messages):
    pre,opening_spend=session
    body=packed({**OPTIONS,'messages':messages})
    previous=db.execute('SELECT * FROM attempt WHERE id=?',(aid,)).fetchone()
    if previous:
        if previous['req']!=body or previous['state']!=state or previous['period']!=period:
            raise Pause('A repeated ID changed prompt or state: '+aid)
        if previous['raw'] is None or previous['cost'] is None or previous['result'] is None:
            raise Pause('Unresolved first attempt: '+aid)
        result=json.loads(previous['result'])
    else:
        budget=spent(db)
        reserve=reserve_for(body,pre['route'])
        maximum=Decimal(load_meta(db,'opening_funding')['stage_limit_usd'])
        additional=budget-opening_spend
        available=min(maximum-budget,remaining_key(pre)-additional,Decimal(pre['account_available_usd'])-additional)
        if available<reserve or db.execute('SELECT COUNT(*) FROM attempt').fetchone()[0]>=MAX_CALLS:
            raise Pause(f'Budget or count stop before {aid}. Confirmed USD {budget}, required reserve {reserve}.')
        unresolved=db.execute('SELECT id FROM attempt WHERE raw IS NULL OR cost IS NULL OR result IS NULL').fetchone()
        if unresolved:
            raise Pause('Unresolved first attempt: '+unresolved['id'])
        with db:
            db.execute('INSERT INTO attempt(id,period,state,start,req,reserve) VALUES (?,?,?,?,?,?)',
                       (aid,period,state,now(),body,str(reserve)))
        try:
            status,raw=provider.post(body)
        except Exception as exc:
            status,raw=0,packed({'transport_exception':type(exc).__name__,
                                 'underlying_exception':type(exc.__cause__).__name__ if exc.__cause__ else None})
        with db:
            db.execute('UPDATE attempt SET http=?,raw=?,received=? WHERE id=?',(status,raw,now(),aid))
        result=parse_receipt(status,raw,state)
        with db:
            db.execute('UPDATE attempt SET provider_id=?,cost=?,result=? WHERE id=?',
                       (result['provider_request_id'],result['charge'],packed(result),aid))
        if result['charge'] is None:
            pending=db.execute('SELECT * FROM attempt WHERE id=?',(aid,)).fetchone()
            print(f'Paused for billing reconciliation at {aid}, HTTP {status}.',flush=True)
            settle_transport(db,provider,pending)
            result=json.loads(db.execute('SELECT result FROM attempt WHERE id=?',(aid,)).fetchone()[0])
    if result['charge'] is None or result['status']=='ROUTE_ERROR':
        raise Pause(f"{aid} requires verification, status {result['status']}, charge {result['charge']}.")
    return result

def projected_event(slot,menu,policy,state,aid,forkid,decision,outcome):
    a,b=OFFERS[menu['A']],OFFERS[menu['B']]
    operator=slot['operator']
    utility=study.values(a,b,study.PREMIUM[operator])
    top=max(utility.values())
    phys={'A':menu['A'],'B':menu['B'],'DECLINE':'DECLINE','NO_EXECUTION':'NO_EXECUTION'}
    chosen=outcome['executed']
    provisional=decision['provisional'] if decision else None
    reviews=outcome['reviews']
    trigger=aid is not None and forkid==aid
    value=utility.get(chosen,0)
    return dict(stage=STAGE,family=slot['family'],recurrence=slot['recurrence'],operator_code=operator,
        period=int(slot['period']),policy=policy,attempt_id=aid,fork_attempt_id=forkid,pair_id=menu['pair_id'],
        offer_A=menu['A'],offer_B=menu['B'],executed_label=chosen,executed_physical=phys[chosen],
        operator_ruling=chosen if reviews else None,qualified_first_referral=trigger,
        carry_rule_before=state in ('RULE','UPFRONT'),carry_rule_after=policy=='UPFRONT' or (policy=='RULE' and (state=='RULE' or trigger)),
        review_count=reviews,later_clause_issued=outcome['new_rules'],provisional_label=provisional,
        best_physical_set=sorted(phys[k] for k,v in utility.items() if v==top),
        provisional_value_100th_c=utility.get(provisional),executed_value_100th_c=value,best_value_100th_c=top,
        loss_100th_c=top-value,immediate_recovered_100th_c=(value-utility[provisional] if reviews and decision else None),
        valid_first_attempt=None if aid is None else decision is not None)

def put_events(db,events):
    with db:
        for event in events:
            key=tuple(event[f] for f in ('family','recurrence','operator_code','period','policy'))
            data=packed(event)
            old=db.execute('SELECT body FROM event WHERE family=? AND recurrence=? AND operator=? AND period=? AND policy=?',key).fetchone()
            if old is None:
                db.execute('INSERT INTO event VALUES (?,?,?,?,?,?)',(*key,data))
            elif old[0]!=data:
                raise Pause('Event differs on restart: '+str(key))

def prior_fork(db,slot):
    key=(slot['family'],slot['recurrence'],slot['operator'],int(slot['period']))
    records=db.execute("SELECT body FROM event WHERE family=? AND recurrence=? AND operator=? AND period<? AND policy='RULE' ORDER BY period DESC",key)
    for row in records:
        event=json.loads(row[0])
        if event['later_clause_issued']:
            return event['attempt_id']
    return None

def purchase(db,provider,session,slot):
    period=int(slot['period'])
    menu=MENUS[slot['family'],slot['recurrence'],period]
    a,b=OFFERS[menu['A']],OFFERS[menu['B']]
    aid=slot['attempt_slot']; flag=slot['slot']; op=slot['operator']
    fork=prior_fork(db,slot) if flag.startswith('REF_') else None
    if flag=='REF_RULE_IF_PRIOR_TRIGGER' and not fork:
        with db:
            db.execute('INSERT OR IGNORE INTO skipped VALUES (?,?)',(aid,'No qualifying referral before this period.'))
        return
    state=flag
    if flag=='REF_PRIMARY':
        state='CASE' if fork else 'SHARED'
    elif flag=='REF_RULE_IF_PRIOR_TRIGGER':
        state='RULE'
    r=submit(db,provider,session,aid,period,state,study.render_state(a,b,period,state,op))
    decision=r['decision']; outcomes=study.prescribed_step(a,b,study.PREMIUM[op],state,r['content'] if decision else None)
    if state=='SHARED':
        policies=('CASE','RULE')
        if len(outcomes)==2:
            fork=aid
        else:
            outcomes=outcomes*2
    else:
        policies=(state,)
    put_events(db,[projected_event(slot,menu,policy,state,aid,fork,decision,out)
                   for policy,out in zip(policies,outcomes,strict=True)])

def close_period(db,period):
    full=[]
    for (family,rec,t),menu in MENUS.items():
        if t!=period:
            continue
        for op,k in study.PREMIUM.items():
            chosen=study.ruling(OFFERS[menu['A']],OFFERS[menu['B']],k)
            slot={'family':family,'recurrence':rec,'operator':op,'period':t}
            full.append(projected_event(slot,menu,'REVIEW_ALL','REVIEW_ALL',None,None,None,
                        {'executed':chosen,'reviews':1,'new_rules':0}))
    put_events(db,full)
    if db.execute('SELECT COUNT(*) FROM event WHERE period=?',(period,)).fetchone()[0]!=PER_PERIOD:
        raise Pause(f'Incomplete policy-period records in period {period}.')

def run(db,provider,through):
    session=start(db,provider)
    for p in range(1,through+1):
        closure=load_meta(db,f'closed_period_{p:02d}')
        if closure:
            if db.execute('SELECT COUNT(*) FROM event WHERE period=?',(p,)).fetchone()[0]!=PER_PERIOD:
                raise Pause('A completed period is missing economic records.')
            continue
        if p>1:
            session=start(db,provider)
        for s in SLOTS:
            if s['period']==p:
                purchase(db,provider,session,s)
        close_period(db,p)
        count=db.execute('SELECT COUNT(*) FROM attempt').fetchone()[0]
        total=spent(db); mean=total/count
        summary={'period':p,'utc':now(),'physical_first_attempts':count,'cumulative_cost_usd':str(total),
                 'executed_or_skipped_slots':count+db.execute('SELECT COUNT(*) FROM skipped').fetchone()[0],
                 'projection_at_remaining_candidate_slots_usd':str(total+mean*sum(row['period']>p for row in SLOTS))}
        with db:
            db.execute('INSERT INTO meta VALUES (?,?)',(f'closed_period_{p:02d}',packed(summary)))
        print(f'Closed period {p}/12. {count} first attempts, USD {total}.',flush=True)
    return session

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--through',type=int,choices=range(13),required=True,metavar='0..12')
    args=parser.parse_args()
    try:
        with exclusive(args.out):
            db=opened(args.out); provider=LiveProvider()
            try:
                run(db,provider,args.through)
            finally:
                provider.close(); db.close()
    except Pause as exc:
        print('PAUSED: '+str(exc),flush=True)
        return 2
    return 0
if __name__=='__main__':
    sys.exit(main())
