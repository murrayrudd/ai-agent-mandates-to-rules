"""Independent receipt, menu, branch, accounting and coverage audit for the pilot."""
import collections
import json
from decimal import Decimal
import collector as c
import evidence

def verify(db,root):
    summary,attempts,events=evidence.export(db,root)
    evidence.validate(summary,attempts,events)
    receipts=[json.loads(x) for x in (root/'receipts.jsonl').read_text().splitlines()]
    paid={r['id']:r for r in receipts}
    quals=json.loads((root/'qualification.json').read_text())
    assert all(r['id'] in c.QUAL_KEYS for r in quals)
    if attempts:
        assert len(quals)==8 and all(q['correct'] for q in quals)
    # Price the token classes independently wherever the provider supplies counts.
    prices={k:Decimal(v) for k,v in {'input':'.000002','cached':'.0000001','output':'.00001'}.items()}
    max_price_difference=Decimal(0)
    for rec in receipts:
        raw=(root/rec['request_file']).read_bytes()
        assert c.sha(raw)==rec['request_sha256']
        req=json.loads(raw)
        assert req['model']==c.MODEL and req['provider']['only']==['openai']
        assert req['provider']['allow_fallbacks'] is False and req['reasoning']=={'effort':'medium'}
        assert req['max_tokens']==8192 and not req.get('tools') and len(req['messages'])==2
        if not rec['first_reply_file']:
            continue
        reply=(root/rec['first_reply_file']).read_bytes()
        assert c.sha(reply)==rec['first_reply_sha256']
        if rec['billed_usd'] is None:
            continue
        assert Decimal(rec['billed_usd'])<=Decimal(rec['reserve_usd'])
        if rec['http_status']==0 and rec['provider_id'] is None:
            info=db.execute('SELECT body FROM meta WHERE id=?',('reconciliation_'+rec['id'],)).fetchone()
            assert info is not None
            recon=json.loads(info[0])
            assert rec['billed_usd']==recon['reconciled_charge_usd']=='0'
            assert recon['original_response_or_error_sha256']==rec['first_reply_sha256']
            assert all(Decimal(m['dedicated_key_usage_usd'])==Decimal(recon['other_confirmed_charges_usd'])
                       for m in recon['samples'])
            continue
        assert rec['returned_model'] in (c.MODEL,c.TARGET) and rec['provider']=='OpenAI'
        resp=json.loads(reply,parse_float=str)
        assert Decimal(str(resp['usage']['cost']))==Decimal(rec['billed_usd'])
        if all(rec[k] is not None for k in ('in_tokens','cached_in_tokens','out_tokens')):
            ti,tc,to=(rec[k] for k in ('in_tokens','cached_in_tokens','out_tokens'))
            expected=(ti-tc)*prices['input']+tc*prices['cached']+to*prices['output']
            max_price_difference=max(max_price_difference,abs(Decimal(rec['billed_usd'])-expected))
    assert len({r['provider_id'] for r in receipts if r['provider_id']})==sum(r['provider_id'] is not None for r in receipts)
    assert sum((Decimal(x['billed_usd']) for x in receipts if x['billed_usd'] is not None),Decimal(0))<=c.CAP
    for q in c.QUAL:
        if q['id'] in paid:
            req=json.loads((root/paid[q['id']]['request_file']).read_bytes())
            assert req['messages']==c.study.qualification_messages(q)
    by_group=collections.defaultdict(dict)
    for e in events:
        by_group[(e['family'],e['recurrence'],e['operator_code'],e['period'])][e['policy']]=e
    record_by_id={r['attempt_id']:r for r in attempts}
    complete=set(summary['complete_periods'])
    for fam in ('P001','P002'):
        for recurrence in ('low','high'):
            for op,k in c.study.PREMIUM.items():
                fork=None
                for t in sorted(complete):
                    e=by_group[(fam,recurrence,op,t)]
                    m=c.MENUS[fam,recurrence,t]
                    a,b=c.OFFERS[m['A']],c.OFFERS[m['B']]
                    vals=c.study.values(a,b,k)
                    top=max(vals.values())
                    assert set(e)=={'REVIEW_ALL','STANDING','CASE','RULE','UPFRONT'}
                    assert e['REVIEW_ALL']['executed_label']==c.study.ruling(a,b,k)
                    before=fork
                    for policy,event in e.items():
                        assert (event['offer_A'],event['offer_B'])==(m['A'],m['B'])
                        assert event['loss_100th_c']==top-vals.get(event['executed_label'],0)
                        aid=event['attempt_id']
                        if not aid:
                            continue
                        att=record_by_id[aid]
                        if policy in ('CASE','RULE'):
                            assert att['state_before']==(policy if before else 'SHARED')
                        else:
                            assert att['state_before']==policy
                        req=json.loads((root/paid[aid]['request_file']).read_bytes())
                        assert req['messages']==c.study.render_state(a,b,t,att['state_before'],op)
                        eligible=(att['status']=='VALID' and att['disposition']=='REFER' and
                                  att['issue']=='CONTROL' and a.keys!=b.keys and not before and policy in ('CASE','RULE'))
                        if eligible:
                            fork=aid
                        assert event['qualified_first_referral']==eligible
                        assert event['later_clause_issued']==(eligible and policy=='RULE')
                        assert event['carry_rule_before']==(policy=='UPFRONT' or (policy=='RULE' and before is not None))
                        if att['status']=='VALID' and att['disposition']=='REFER':
                            assert event['review_count']==1 and event['executed_label']==c.study.ruling(a,b,k)
                            assert event['immediate_recovered_100th_c']==top-vals[att['provisional']]
                        if att['status']=='VALID' and att['disposition']=='ACT':
                            assert event['executed_label']==att['provisional'] and event['review_count']==0
                    if before is None:
                        assert e['CASE']['attempt_id']==e['RULE']['attempt_id']
                    else:
                        assert e['CASE']['attempt_id']!=e['RULE']['attempt_id']
    checks={'attempt_and_event_schemas':'pass','prompt_reconstruction':'pass',
            'single_provider_and_budget':'pass','shared_prefix_and_fork_timing':'pass',
            'independent_event_ledger':'pass','largest_absolute_token_price_crosscheck_difference_usd':str(max_price_difference)}
    evidence.write_json(root/'integrity_checks.json',checks)
    return summary,attempts,events,checks
