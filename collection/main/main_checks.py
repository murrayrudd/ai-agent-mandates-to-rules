"""Rebuild each completed block from its first receipts and return masked operational counts."""
import json
import time
from decimal import Decimal
import collector as c


def require(value, message):
    if not value:
        raise c.Pause(message)


def reconcile(db, provider):
    opening=c.load_meta(db,'opening_funding')
    amount=c.spent(db)
    expected=Decimal(opening['key_usage_usd'])+amount
    readings=[]
    for delay in (0,8,15,25,35,45):
        if delay:
            time.sleep(delay)
        k=provider.key_state()
        meter=Decimal(str(k['usage']))
        readings.append({'utc':c.now(),'key_usage_usd':str(meter)})
        if meter==expected:
            break
    credit=provider.credit_balance()
    account_change=Decimal(opening['available_account_credit_usd'])-credit
    return {'key_meter_reconciled':meter==expected,'paid_main_usd':str(amount),
            'prior_project_usd':str(c.PRIOR_SPEND),'paid_all_stages_usd':str(c.PRIOR_SPEND+amount),
            'account_credit_usd':str(credit),'account_balance_change_usd':str(account_change),
            'account_change_minus_main_debit_usd':str(account_change-amount),
            'available_key_allowance_usd':str(k['limit_remaining']),'key_expiry_utc':k.get('expires_at'),
            'remaining_main_ceiling_usd':str(Decimal(opening['stage_limit_usd'])-amount),
            'meter_readings':readings}


def check_block(db,members):
    slots=[s for s in c.SLOTS if s['family'] in members]
    def rows(table, field='id'):
        return db.execute(f'SELECT * FROM {table} WHERE substr({field},1,4) BETWEEN ? AND ? ORDER BY rowid',
                          (members[0],members[-1])).fetchall()
    receipts={r['id']:r for r in rows('attempt')}
    skipped={r['id'] for r in rows('skipped')}
    require(not skipped.intersection(receipts),'A skipped slot also has a paid attempt.')
    require([s['attempt_slot'] for s in slots if s['attempt_slot'] not in skipped]==list(receipts),
            'First attempts do not follow the frozen block order.')
    require({s['attempt_slot'] for s in slots}==set(receipts)|skipped,'An assigned slot is missing or unexpected.')
    events={(r['family'],r['operator'],r['recurrence'],r['period'],r['policy']):json.loads(r['body'])
            for r in rows('event','family')}
    require(len(events)==len(members)*2*2*12*len(c.POLICIES),'Wrong policy-period count.')
    parsed={}
    ids=set()
    failures=0
    for aid,row in receipts.items():
        require(row['raw'] is not None and row['result'] is not None and row['cost'] is not None,
                'A receipt has an unresolved response or charge.')
        result=json.loads(row['result'])
        obj=c.parse_receipt(row['http'],row['raw'],row['state'])
        require((obj['status'],obj['decision'])==(result['status'],result['decision']),
                'The raw response and parsed first attempt differ.')
        if row['provider_id']:
            require(row['provider_id'] not in ids,'A provider generation ID is duplicated.')
            ids.add(row['provider_id'])
        cost=Decimal(row['cost'])
        require(0<=cost<=Decimal(row['reserve']),'Charge outside the reserved interval.')
        if result.get('charge_source','provider usage receipt')=='provider usage receipt':
            require(obj['charge'] is not None and Decimal(obj['charge'])==cost,'Raw billing disagrees with the ledger.')
            require((obj['upstream'],obj['model']) in (('OpenAI',c.MODEL),('OpenAI',c.TARGET)),'Wrong model route.')
        else:
            recon=c.load_meta(db,'reconciliation_'+aid)
            require(recon and Decimal(recon['charge'])==cost and recon['original_response_or_error_sha256']==c.sha(row['raw']),
                    'Uncorroborated reconciled billing record.')
        failures+=obj['status']!='VALID'
        parsed[aid]=obj
    for family in members:
        for op,k in c.study.PREMIUM.items():
            for rec in ('low','high'):
                fork=None
                for period in range(1,13):
                    menu=c.MENUS[family,rec,period]
                    a,b=(c.OFFERS[menu[x]] for x in ('A','B'))
                    utility=c.study.values(a,b,k)
                    ruling=c.study.ruling(a,b,k)
                    prefix=f'{family}-{rec}-{op}-t{period:02d}-'
                    before=fork
                    for policy in c.POLICIES:
                        e=events[family,op,rec,period,policy]
                        require(e['stage']==c.STAGE and e['offer_A']==menu['A'] and e['offer_B']==menu['B'],
                                'Menu or study stage differs from the frozen assignment.')
                        if policy=='REVIEW_ALL':
                            require(e['attempt_id'] is None and e['executed_label']==ruling and e['review_count']==1
                                    and e['loss_100th_c']==0,'The programmed approval benchmark differs from the operator optimum.')
                            continue
                        suffix=policy if policy in ('STANDING','UPFRONT') else (
                            'REF_RULE_IF_PRIOR_TRIGGER' if policy=='RULE' and before else 'REF_PRIMARY')
                        aid=prefix+suffix
                        require(e['attempt_id']==aid and aid in receipts,'A policy follows the wrong physical attempt.')
                        seen=receipts[aid]; result=parsed[aid]
                        state=policy if policy in ('STANDING','UPFRONT') or before else 'SHARED'
                        expected_body=c.packed({**c.OPTIONS,'messages':c.study.render_state(a,b,period,state,op)})
                        require(seen['state']==state and seen['req']==expected_body,'Wrong state or displayed prompt.')
                        decision=result['decision']
                        referred=bool(decision and decision['disposition']=='REFER')
                        trigger=bool((not before) and referred and decision['issue']=='CONTROL'
                                     and a.keys!=b.keys and policy in ('CASE','RULE'))
                        if trigger:
                            fork=aid
                        require(bool(e['qualified_first_referral'])==trigger and bool(e['later_clause_issued'])==(trigger and policy=='RULE'),
                                'The eligible referral or reusable clause flag differs.')
                        require(bool(e['carry_rule_before'])==(policy=='UPFRONT' or (policy=='RULE' and bool(before))),
                                'Clause scope differs at entry.')
                        require(bool(e['carry_rule_after'])==(policy=='UPFRONT' or (policy=='RULE' and bool(before or trigger))),
                                'Clause retention differs at exit.')
                        chosen=ruling if referred else decision['provisional'] if decision else 'NO_EXECUTION'
                        require(e['executed_label']==chosen and e['review_count']==int(referred) and
                                e['loss_100th_c']==max(utility.values())-utility.get(chosen,0),'Economic projection differs.')
                        if referred:
                            require(e['immediate_recovered_100th_c']==max(utility.values())-utility[decision['provisional']],
                                    'Incorrect immediate correction.')
                    optional_slot=prefix+'REF_RULE_IF_PRIOR_TRIGGER'
                    if optional_slot in skipped:
                        require(before is None,'An eligible post-referral request was skipped.')
    return {'families':len(members),'first_family':members[0],'last_family':members[-1],
            'candidate_slots':len(slots),'paid_or_failed_first_attempts':len(receipts),'conditional_skips':len(skipped),
            'unique_provider_ids':len(ids),'invalid_or_failed_first_attempts':failures,'policy_period_records':len(events),
            'checks':'passed','choice_comparisons':'masked'}
