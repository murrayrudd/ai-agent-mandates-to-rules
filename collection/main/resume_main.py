"""Run the frozen collector and reconcile a billed request whose reply was lost."""
import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import collector as c


METER_METHOD = 'isolated key and prepaid account readings for one outstanding first attempt'
UNSETTLED = 'Dedicated key meter does not reconcile with the other charges. Preserve the first attempt.'


def settled_meter_charge(samples, expected_usage, expected_credit, reserve):
    if len(samples) < 2:
        return None
    previous, latest = samples[-2:]
    usage = Decimal(latest['usage_usd'])
    if usage != Decimal(previous['usage_usd']):
        return None
    charge = usage - expected_usage
    if not charge.is_finite() or not 0 <= charge <= reserve:
        return None
    for observation in (previous, latest):
        if expected_credit - Decimal(observation['account_credit_usd']) != charge:
            return None
    return charge


def prior_balances(db, recorded):
    origin = c.load_meta(db, 'opening_funding')
    return (Decimal(origin['key_usage_usd']) + recorded,
            Decimal(origin['available_account_credit_usd']) - recorded)


def recover_meter(db, provider):
    # The caller holds the same exclusive lock used by the original collector.
    pending = db.execute('SELECT * FROM attempt WHERE cost IS NULL').fetchall()
    if len(pending) != 1:
        raise c.Pause('A meter reconciliation requires exactly one outstanding first attempt.')
    row = pending[0]
    interrupted = all(row[field] is None for field in ('raw', 'http', 'received', 'provider_id', 'result'))
    result = json.loads(row['result']) if row['result'] else {}
    if not interrupted and (row['provider_id'] or result.get('provider_request_id') or result.get('charge') is not None
            or row['http'] != 0 or result.get('status') != 'TRANSPORT_ERROR' or not row['raw'] or not row['received']):
        raise c.Pause('The outstanding request requires the original receipt reconciliation.')
    recorded = c.spent(db)
    expected_usage, expected_credit = prior_balances(db, recorded)
    origin = c.load_meta(db, 'opening_funding')
    declared = provider.key_state()
    if (declared.get('expires_at') != origin['key_expires_at']
            or Decimal(str(declared['limit'])) != Decimal(str(origin['key_limit_usd']))
            or declared.get('limit_reset') is not None):
        raise c.Pause('The key funding epoch changed before reconciliation.')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(row['received'] or row['start'])).total_seconds()
    minimum = 210 if interrupted else 90
    if age < minimum:
        time.sleep(minimum - max(0, age))
    samples = []
    for attempt in range(5):
        if attempt:
            time.sleep(35)
        state = provider.key_state()
        credit = provider.credit_balance()
        samples.append({'utc': c.now(), 'usage_usd': str(state['usage']), 'account_credit_usd': str(credit)})
        charge = settled_meter_charge(samples, expected_usage, expected_credit, Decimal(row['reserve']))
        if charge is not None:
            break
    else:
        raise c.Pause('Key and account readings cannot corroborate the outstanding charge.')
    raw = row['raw']
    if interrupted:
        raw = c.packed({'transport_exception': 'ProcessInterrupted', 'description': 'Local journal observation: no provider reply or exception was saved before interruption.'})
        result = c.parse_receipt(0, raw, row['state'])
    evidence = {'method': METER_METHOD, 'charge': str(charge), 'samples': samples,
                'recorded_main_usd': str(recorded), 'expected_key_usage_usd': str(expected_usage),
                'expected_account_credit_usd': str(expected_credit), 'single_pending_attempt_id': row['id'],
                'original_response_or_error_sha256': c.sha(raw),
                'raw_record_source': 'local interruption marker' if interrupted else 'saved transport error',
                'provider_receipt_saved': False}
    result.update(charge=str(charge), charge_source=METER_METHOD)
    with db:
        db.execute('INSERT INTO meta VALUES (?,?)', ('reconciliation_' + row['id'], c.packed(evidence)))
        updated = db.execute('UPDATE attempt SET cost=?,result=?,raw=?,http=?,received=? WHERE id=? AND cost IS NULL',
                             (str(charge), c.packed(result), raw, row['http'] or 0,
                              row['received'] or c.now(), row['id']))
        if updated.rowcount != 1:
            raise c.Pause('An outstanding charge changed during reconciliation.')
    print(f"Reconciled {row['id']} at USD {charge} from the key and the account. Technical nonexecution recorded.",
          flush=True)


def verify_recoveries(db):
    rows = db.execute("SELECT rowid,* FROM attempt WHERE json_extract(result,'$.charge_source')=?", (METER_METHOD,))
    count = 0
    for row in rows:
        earlier = db.execute('SELECT cost FROM attempt WHERE rowid < ?', (row['rowid'],))
        recorded = sum((Decimal(item[0]) for item in earlier), Decimal(0))
        usage, credit = prior_balances(db, recorded)
        proof = c.load_meta(db, 'reconciliation_' + row['id'])
        if (not proof or proof['single_pending_attempt_id'] != row['id'] or proof['method'] != METER_METHOD
                or proof['original_response_or_error_sha256'] != c.sha(row['raw'])
                or Decimal(proof['recorded_main_usd']) != recorded
                or Decimal(proof['expected_key_usage_usd']) != usage
                or Decimal(proof['expected_account_credit_usd']) != credit
                or Decimal(proof['charge']) != Decimal(row['cost'])
                or settled_meter_charge(proof['samples'], usage, credit, Decimal(row['reserve'])) != Decimal(row['cost'])
                or row['provider_id'] is not None or json.loads(row['result'])['status'] != 'TRANSPORT_ERROR'):
            raise c.Pause('Meter reconciliation evidence does not verify for ' + row['id'])
        count += 1
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--through', type=int, choices=(24, 48), required=True)
    args = parser.parse_args()
    try:
        with c.exclusive(args.out):
            db = c.opened(args.out)
            provider = None
            try:
                provider = c.LiveProvider()
                c.manifest(db, provider.mode)
                verify_recoveries(db)
                pending = db.execute("SELECT COUNT(*) FROM attempt WHERE cost IS NULL AND provider_id IS NULL AND ((http=0 AND raw IS NOT NULL AND result IS NOT NULL) OR (http IS NULL AND raw IS NULL AND result IS NULL AND received IS NULL))").fetchone()[0]
                if pending:
                    recover_meter(db, provider)
                while True:
                    try:
                        c.run(db, provider, args.through)
                        break
                    except c.Pause as error:
                        if str(error) != UNSETTLED:
                            raise
                        recover_meter(db, provider)
                verify_recoveries(db)
            finally:
                if provider:
                    provider.close()
                db.close()
    except c.Pause as error:
        print('PAUSED: ' + str(error), flush=True)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
