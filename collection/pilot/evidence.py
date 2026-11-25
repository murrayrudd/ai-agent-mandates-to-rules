"""Export the frozen raw first attempts and their economic projections. No network."""
import argparse
import collections
import json
import shutil
from decimal import Decimal
from pathlib import Path
import collector as c

def write_json(path, data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def export(db,dest):
    dest.mkdir(parents=True,exist_ok=True)
    rawdir=dest/'raw'; rawdir.mkdir(exist_ok=True)
    attempts=[]; qualification=[]; events=[]; receipts=[]; op_status=collections.Counter()
    slots={s['attempt_slot']:s for s in c.SLOTS}
    for row in db.execute('SELECT * FROM attempt ORDER BY rowid'):
        aid=row['id']; raw=row['raw']; state=row['state']; result=json.loads(row['result']) if row['result'] else {}
        request=json.loads(row['req']); base='raw/'+aid
        (dest/(base+'.request.json')).write_bytes(row['req'])
        if raw is not None:
            (dest/(base+'.response')).write_bytes(raw)
        receipts.append({'id':aid,'started_utc':row['start'],'received_utc':row['received'],
            'request_file':base+'.request.json','request_sha256':c.sha(row['req']),
            'first_reply_file':base+'.response' if raw is not None else None,
            'first_reply_sha256':c.sha(raw) if raw is not None else None,'http_status':row['http'],
            'reserve_usd':row['reserve'],'billed_usd':row['cost'],'returned_model':result.get('model'),
            'provider':result.get('upstream'),'provider_id':row['provider_id'],'fingerprint':result.get('fingerprint'),
            **{k:result.get(k) for k in ('in_tokens','out_tokens','reasoning_tokens','cached_in_tokens')}})
        if state=='QUAL':
            ans=(result.get('decision') or {}).get('answer')
            qualification.append({'id':aid,'received_answer':ans,'prescribed_answer':c.QUAL_KEYS[aid],
                'correct':result.get('status')=='VALID' and ans==c.QUAL_KEYS[aid],
                'status':result.get('status','PENDING'),'billed_usd':row['cost']})
            continue
        if not result or raw is None:
            continue
        s=slots[aid]; menu=c.MENUS[s['family'],s['recurrence'],row['period']]
        clause=None
        if state in ('RULE','UPFRONT'):
            clause=c.sha(c.study.textfile('clause.txt').format(premium_c=c.study.PREMIUM[s['operator']]).encode('utf8'))
        decision=result.get('decision') or {}
        attempts.append(dict(attempt_id=aid,stage='pilot',family=s['family'],operator_code=s['operator'],
            recurrence=s['recurrence'],period=row['period'],state_before=state,model_snapshot=c.TARGET,
            upstream=result['upstream'],provider_request_id=row['provider_id'],inference_config_hash=c.INPUT_HASH,
            design_version=c.study.D['version'],menu_id=menu['pair_id'],economic_root=menu['economic_root'],
            offer_A=menu['A'],offer_B=menu['B'],authorized_clause_sha256=clause,
            messages_sha256=c.sha(c.study.jsonbytes(request['messages'])),raw_request_path=base+'.request.json',
            raw_response_or_error_path=base+'.response',raw_response_or_error_sha256=c.sha(raw),
            request_started_utc=row['start'],status=result['status'],in_tokens=result['in_tokens'],
            out_tokens=result['out_tokens'],billed_usd=row['cost'],provisional=decision.get('provisional'),
            disposition=decision.get('disposition'),issue=decision.get('issue')))
        op_status[(state,result['status'])]+=1
    events=[json.loads(r[0]) for r in db.execute('SELECT body FROM event ORDER BY family,recurrence,operator,period,policy')]
    for name,records in [('purchase_attempts',attempts),('policy_events',events),('receipts',receipts)]:
        (dest/(name+'.jsonl')).write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in records),encoding='utf8')
    write_json(dest/'qualification.json',qualification)
    write_json(dest/'skipped_conditional_slots.json',[dict(r) for r in db.execute('SELECT * FROM skipped ORDER BY id')])
    write_json(dest/'route_and_key_limits.json',[json.loads(r[0]) for r in db.execute('SELECT body FROM preflight ORDER BY observed_at')])
    for k,body in db.execute('SELECT id,body FROM meta'):
        write_json(dest/(k+'.json'),json.loads(body))
    qcost=sum((Decimal(r['billed_usd']) for r in qualification if r['billed_usd'] is not None),Decimal(0))
    pcost=sum((Decimal(r['billed_usd']) for r in attempts if r['billed_usd'] is not None),Decimal(0))
    total=c.spent(db)
    ctr=collections.Counter(r['period'] for r in events)
    summary={'mode':json.loads(db.execute("SELECT body FROM meta WHERE id='manifest'").fetchone()[0])['mode'],
        'qualification_requests':len(qualification),'qualification_correct':sum(q['correct'] for q in qualification),
        'qualification_usd':str(qcost),'purchase_count':len(attempts),'purchase_usd':str(pcost),
        'total_usd':str(total),'unresolved_first_attempts':db.execute(
            'SELECT COUNT(*) FROM attempt WHERE cost IS NULL OR raw IS NULL OR result IS NULL').fetchone()[0],
        'unique_provider_ids':len({r['provider_id'] for r in receipts if r['provider_id']}),
        'purchase_status_by_state':{f'{s} {v}':n for (s,v),n in op_status.items()},
        'complete_periods':[p for p,n in sorted(ctr.items()) if n==40],
        'policy_period_events':len(events),'skipped_conditional_calls':db.execute('SELECT COUNT(*) FROM skipped').fetchone()[0],
        'first_qualifying_referrals':sum(e['later_clause_issued'] for e in events),
        'operator_review_all_events':sum(e['policy']=='REVIEW_ALL' for e in events)}
    write_json(dest/'summary.json',summary)
    return summary,attempts,events

def validate(summary,attempts,events):
    import jsonschema
    for name,objects in [('attempt',attempts),('path_event',events)]:
        schema=json.loads((c.DESIGN/'spec'/(name+'.schema.json')).read_text())
        validator=jsonschema.Draft202012Validator(schema)
        for obj in objects:
            validator.validate(obj)
    paid={r['attempt_id']:r for r in attempts}
    assert len(paid)==len(attempts)
    assert len({(e['family'],e['recurrence'],e['operator_code'],e['period'],e['policy']) for e in events})==len(events)
    projections=collections.defaultdict(list)
    for e in events:
        if e['attempt_id']:
            a=paid[e['attempt_id']]
            assert (a['offer_A'],a['offer_B'])==(e['offer_A'],e['offer_B'])
            projections[e['attempt_id']].append(e)
        if e['later_clause_issued']:
            assert e['attempt_id']==e['fork_attempt_id']
    for aid,arr in projections.items():
        a=paid[aid]
        assert len(arr)==(2 if a['state_before']=='SHARED' else 1)
        if len(arr)==2:
            assert {e['policy'] for e in arr}=={'CASE','RULE'}
            assert len({(e['executed_physical'],e['review_count'],e['loss_100th_c']) for e in arr})==1
    if summary['complete_periods']==list(range(1,13)):
        assert set(projections)==set(paid)
        assert len(events)==480 and summary['operator_review_all_events']==96
        assert len(attempts)+summary['skipped_conditional_calls']==len(c.SLOTS)
        assert sum(e['later_clause_issued'] for e in events)<=8

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('journal_folder',type=Path)
    parser.add_argument('export_folder',type=Path)
    a=parser.parse_args()
    db=c.opened(a.journal_folder)
    s,at,ev=export(db,a.export_folder)
    validate(s,at,ev)
    print(json.dumps(s,indent=2))
