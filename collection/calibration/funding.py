"""One final read-only balance and first-receipt reconciliation."""
import argparse
from decimal import Decimal
from pathlib import Path
import time
import collector as c

def close(folder):
    with c.exclusive(folder):
        db=c.opened(folder); provider=c.LiveProvider()
        try:
            if any(c.load_meta(db,f'closed_period_{p:02d}') is None for p in range(1,13)):
                raise c.Pause('The calibration is still incomplete.')
            if db.execute('SELECT count(*) FROM attempt WHERE cost IS NULL OR raw IS NULL OR result IS NULL').fetchone()[0]:
                raise c.Pause('An outstanding first attempt requires reconciliation.')
            opening=c.load_meta(db,'opening_funding')
            base=Decimal(opening['key_usage_usd']); stage=c.spent(db)
            readings=[]
            for delay in [0,8,15,25,35,45,50]:
                if delay: time.sleep(delay)
                k=provider.key_state()
                now_usd=Decimal(str(k['usage']))
                readings.append({'utc':c.now(),'key_usage_usd':str(now_usd)})
                if now_usd==base+stage: break
            account_start=Decimal(opening['available_account_credit_usd'])
            account=provider.credit_balance()
            for delay in (8,15,25):
                if account_start-account>=stage: break
                time.sleep(delay)
                account=provider.credit_balance()
            document={'checked_utc':c.now(),'pilot_key_usage_at_start_usd':str(base),
                        'calibration_first_attempt_charges_usd':str(stage),
                        'project_usage_on_dedicated_key_usd':str(now_usd),
                        'key_meter_minus_combined_receipts_usd':str(now_usd-base-stage),
                        'key_meter_reconciled':now_usd==base+stage,'account_credit_after_usd':str(account),
                        'account_credit_at_open_usd':str(account_start),
                        'account_balance_change_usd':str(account_start-account),
                        'account_balance_change_minus_calibration_usd':str(account_start-account-stage),
                        'dedicated_key_limit_usd':str(k['limit']),'remaining_key_allowance_usd':str(k['limit_remaining']),
                        'dedicated_key_expires_at':k.get('expires_at'),
                        'observations':readings}
            with db:
                db.execute("INSERT OR REPLACE INTO meta VALUES ('closing_funding',?)",(c.packed(document),))
            print(c.packed(document).decode(),flush=True)
        finally:
            provider.close(); db.close()
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path)
    close(parser.parse_args().folder)
