"""Reconcile a single failed send against the isolated pilot key without redispatch."""
import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import collector as c

def reconcile(folder,aid):
    with c.exclusive(folder):
        db=c.opened(folder); provider=c.LiveProvider()
        try:
            unresolved=db.execute('SELECT * FROM attempt WHERE cost IS NULL ORDER BY rowid').fetchall()
            if len(unresolved)!=1 or unresolved[0]['id']!=aid:
                raise c.Pause('Exactly the specified outstanding charge is required.')
            entry=unresolved[0]
            result=json.loads(entry['result'] or b'{}')
            if (entry['http']!=0 or entry['provider_id'] is not None or
                result.get('status')!='TRANSPORT_ERROR' or not entry['raw']):
                raise c.Pause('This operation applies only to a retained client transport error.')
            other=c.spent(db)
            readings=[]
            for delay in (0,35):
                if delay: time.sleep(delay)
                key=provider.key_state()
                readings.append({'observed_utc':c.now(),'dedicated_key_usage_usd':str(key['usage']),
                                 'dedicated_key_limit':str(key['limit']),'limit_reset':key['limit_reset']})
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(entry['received'])).total_seconds()
            if (age<90 or any(Decimal(r['dedicated_key_usage_usd'])!=other or r['limit_reset'] is not None
                or Decimal(r['dedicated_key_limit'])>c.CAP for r in readings)):
                raise c.Pause('The independent key meter has not settled to the sum of every other charge.')
            info={'id':aid,'decision':'retain technical nonexecution; resume only at a new unsent ID',
                'evidence':'single in-flight first attempt, exclusive new key, confirmed cost of all other requests, two settled key meter readings, original client error, no model reply',
                'age_after_error_seconds':round(age,2),'other_confirmed_charges_usd':str(other),
                'reconciled_charge_usd':'0','samples':readings,'original_response_or_error_sha256':c.sha(entry['raw'])}
            result['charge']='0';result['charge_source']='dedicated-key meter reconciliation'
            with db:
                db.execute('INSERT INTO meta VALUES (?,?)',('reconciliation_'+aid,c.packed(info)))
                db.execute('UPDATE attempt SET cost=?,result=? WHERE id=? AND cost IS NULL',('0',c.packed(result),aid))
            print(json.dumps(info,indent=2),flush=True)
        finally:
            provider.close();db.close()
if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('journal_folder',type=Path);p.add_argument('attempt_id')
    a=p.parse_args()
    reconcile(a.journal_folder,a.attempt_id)
