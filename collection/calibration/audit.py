"""Audit the reserved calibration assignments, raw receipts and policy projections."""
import collections
import itertools
import json
from decimal import Decimal
import collector as c
import evidence

def verify(db,root):
    summary,attempts,events=evidence.export(db,root)
    evidence.validate(summary,attempts,events)
    recs=[json.loads(s) for s in (root/'receipts.jsonl').read_text().splitlines()]
    receipts={r['id']:r for r in recs}
    physical={a['attempt_id']:a for a in attempts}
    ordered={s['attempt_slot']:idx for idx,s in enumerate(c.SLOTS)}
    assert len(ordered)==2144 and len(receipts)==len(recs)
    order=[ordered[r['id']] for r in recs]
    assert sorted(order)==order
    maximum_price_error=Decimal(0)
    for record in recs:
        aid=record['id']; req=(root/record['request_file']).read_bytes()
        assert c.sha(req)==record['request_sha256']
        obj=json.loads(req); messages=obj.pop('messages')
        assert obj==c.OPTIONS and len(messages)==2 and aid.startswith('D')
        if not record['first_reply_file']: continue
        raw=(root/record['first_reply_file']).read_bytes()
        assert c.sha(raw)==record['first_reply_sha256']
        if record['billed_usd'] is None: continue
        cost=Decimal(record['billed_usd'])
        assert 0<=cost<=Decimal(record['reserve_usd'])
        if record['charge_source']!='provider usage receipt':
            recon=c.load_meta(db,'reconciliation_'+aid)
            assert recon and Decimal(recon['charge'])==cost and recon['original_response_or_error_sha256']==c.sha(raw)
            if 'samples' in recon:
                assert all(Decimal(m['usage_usd'])==Decimal(recon['expected_key_usage_usd']) for m in recon['samples'][-2:])
            continue
        resp=json.loads(raw,parse_float=str)
        assert record['provider']=='OpenAI' and record['returned_model'] in (c.MODEL,c.TARGET)
        assert resp['id']==record['provider_id'] and Decimal(str(resp['usage']['cost']))==cost
        ti,tc,to=(record[n] for n in ('in_tokens','cached_in_tokens','out_tokens'))
        if all(x is not None for x in (ti,tc,to)):
            calc=Decimal(ti-tc)*Decimal('.000002')+Decimal(tc)*Decimal('.0000001')+Decimal(to)*Decimal('.00001')
            maximum_price_error=max(maximum_price_error,abs(calc-cost))
    assert sum((Decimal(r['billed_usd']) for r in recs if r['billed_usd'] is not None),Decimal(0))<=Decimal(c.load_meta(db,'opening_funding')['stage_limit_usd'])
    group=collections.defaultdict(dict)
    for e in events:
        group[(e['family'],e['operator_code'],e['recurrence'],e['period'])][e['policy']]=e
        assert e['stage']==c.STAGE
    closed=sorted(summary['complete_periods'])
    assert closed==list(range(1,len(closed)+1))
    for f,op,rec in itertools.product(c.FAMILIES,c.study.PREMIUM,('low','high')):
        fork=None
        for t in closed:
            ev=group[f,op,rec,t]
            assert set(ev)==set(c.CORE)
            menu=c.MENUS[f,rec,t]
            a,b=(c.OFFERS[menu[k]] for k in ('A','B'))
            values=c.study.values(a,b,c.study.PREMIUM[op]); best=max(values.values())
            before=fork
            assert ev['REVIEW_ALL']['executed_label']==c.study.ruling(a,b,c.study.PREMIUM[op])
            for policy,e in ev.items():
                assert (e['offer_A'],e['offer_B'])==(menu['A'],menu['B'])
                assert e['loss_100th_c']==best-values.get(e['executed_label'],0)
                aid=e['attempt_id']
                if aid is None:
                    assert policy=='REVIEW_ALL'
                    continue
                att=physical[aid]; state=att['state_before']
                expect='STANDING' if policy=='STANDING' else policy if before else 'SHARED'
                assert state==expect
                req=json.loads((root/receipts[aid]['request_file']).read_bytes())
                assert req['messages']==c.study.render_state(a,b,t,state,op)
                trigger=(att['status']=='VALID' and att['disposition']=='REFER' and att['issue']=='CONTROL'
                         and a.keys!=b.keys and not before and policy in ('CASE','RULE'))
                if trigger: fork=aid
                assert e['qualified_first_referral']==trigger and e['later_clause_issued']==(trigger and policy=='RULE')
                assert e['carry_rule_before']==(policy=='RULE' and before is not None)
                assert e['carry_rule_after']==(policy=='RULE' and (before is not None or trigger))
                if att['status']!='VALID':
                    assert e['executed_label']=='NO_EXECUTION' and e['review_count']==0
                elif att['disposition']=='REFER':
                    assert e['review_count']==1 and e['executed_label']==c.study.ruling(a,b,c.study.PREMIUM[op])
                    assert e['immediate_recovered_100th_c']==best-values[att['provisional']]
                else:
                    assert e['executed_label']==att['provisional'] and e['review_count']==0
            assert (ev['CASE']['attempt_id']==ev['RULE']['attempt_id'])==(before is None)
    if len(closed)==12:
        skipped={r[0] for r in db.execute('SELECT id FROM skipped')}
        assert not skipped.intersection(receipts) and set(ordered)==set(receipts).union(skipped)
        assert summary['unresolved_first_attempts']==0
    result={'checks':'passed','periods_audited':len(closed),'fixed_input_banks':'verified',
            'order_and_first_attempts':'verified','prompt_and_price_crosscheck':'verified',
            'max_token_price_difference_usd':str(maximum_price_error),'economic_records':'verified'}
    evidence.write_json(root/'integrity_checks.json',result)
    return summary,attempts,events

