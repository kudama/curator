"""Curator-local Gems reservations; never an account-wide provider spending cap."""
import math
from datetime import datetime
from .store import now
from .errors import UserError


def gems(value, label='Gems allowance'):
    if type(value) not in (int,float) or not math.isfinite(value) or value<0:
        raise UserError(label+' must be a finite nonnegative number')
    return value


def over_budget_message(total, limit, label, count=None):
    options=(' for '+str(count)+' '+('option' if count==1 else 'options')) if count else ''
    return f'Estimated cost: {total:g} Gems{options}. {label}: {limit:g} Gems ({max(0,total-limit):g} Gems over budget).'


class MageBudgets:
    def mage_budget_period(self):
        return datetime.now().astimezone().strftime('%Y-%m')

    def mage_budget_usage(self, period=None):
        period=period or self.mage_budget_period()
        ledger=self.store.get('settings','mage-budget:'+period,{'rows':{}})
        committed=sum(max(row['estimate'],row.get('charged',0)-row.get('refunded',0)) if row['phase'] in {'reserved','unknown'} else max(0,row.get('charged',0)-row.get('refunded',0)) for row in ledger['rows'].values())
        return dict(period=period,committed=committed,limit=self.config().get('mage_monthly_budget',0),rows=ledger['rows'])

    def reserve_mage_budget(self, receipt):
        # Caller owns one Store transaction covering reservation and task admission.
        period=self.mage_budget_period();usage=self.mage_budget_usage(period)
        total=gems(receipt['total'],'Generation estimate')
        cap=receipt.get('batch_limit')
        if cap is not None and total>gems(cap,'Batch budget'):
            raise UserError(over_budget_message(total, cap, 'Curator batch budget', receipt.get('count')))
        monthly=gems(self.config().get('mage_monthly_budget',0),'Monthly Gems allowance')
        if monthly and usage['committed']+total>monthly:
            raise UserError(over_budget_message(total, max(0,monthly-usage['committed']), 'Remaining Curator monthly allowance', receipt.get('count')))
        ledger={'rows':usage['rows']}
        for row in receipt['rows']:
            if row['id'] in ledger['rows']:raise UserError('This generation already has a budget reservation')
            ledger['rows'][row['id']]=dict(estimate=gems(row['quote']['gems']),phase='reserved',created=now(),charged=0,refunded=0)
        self.store.put('settings','mage-budget:'+period,ledger)
        return period

    def reconcile_mage_budget(self, task_id, provider, terminal=False, unsubmitted=False):
        period=provider.get('budget_period')
        if not period:return  # Legacy consent remains valid; do not invent a charge.
        with self.store.transaction():
            ledger=self.store.get('settings','mage-budget:'+period,{'rows':{}})
            row=ledger['rows'].get(task_id)
            if not row:return
            billing=provider.get('billing') or {}
            if unsubmitted and not provider.get('attempted') and not provider.get('request_id'):
                row.update(phase='released',charged=0,refunded=0,updated=now())
            else:
                charged=billing.get('gems_charged');refunded=billing.get('gems_refunded',0)
                # Keep a known charge even when the accompanying refund is malformed.
                # An uncertain response must never create apparent spending room.
                if type(charged) in (int,float) and math.isfinite(charged) and charged>=0:
                    row.update(charged=max(charged,row.get('charged',0)),over_estimate=charged>row['estimate'])
                if type(charged) in (int,float) and math.isfinite(charged) and charged>=0 and type(refunded) in (int,float) and math.isfinite(refunded) and 0<=refunded<=charged:
                    row.update(charged=charged,refunded=refunded,phase='settled' if terminal else 'reserved',over_estimate=charged>row['estimate'],updated=now())
                elif terminal:row.update(phase='unknown',updated=now())
            self.store.put('settings','mage-budget:'+period,ledger)

    def ensure_mage_budget_for_submission(self, task):
        provider=task.get('provider') or {}
        old_period=provider.get('budget_period')
        if not old_period or provider.get('attempted') or provider.get('request_id'):return
        period=self.mage_budget_period()
        with self.store.transaction():
            old=self.store.get('settings','mage-budget:'+old_period,{'rows':{}})
            row=old['rows'].get(task['id'])
            if row and row['phase']=='reserved' and period==old_period:return
            if not row or row['phase'] not in {'released','reserved'}:
                raise UserError('Generation budget outcome needs review before resubmission')
            usage=self.mage_budget_usage(period);monthly=gems(usage['limit'])
            if monthly and usage['committed']+provider['estimate']>monthly:
                raise UserError(over_budget_message(provider['estimate'], max(0,monthly-usage['committed']), 'Remaining Curator monthly allowance', 1))
            row.update(phase='released',charged=0,refunded=0)
            self.store.put('settings','mage-budget:'+old_period,old)
            ledger=self.store.get('settings','mage-budget:'+period,{'rows':{}})
            ledger['rows'][task['id']]=dict(estimate=provider['estimate'],phase='reserved',charged=0,refunded=0,created=now())
            self.store.put('settings','mage-budget:'+period,ledger)
            provider['budget_period']=period
            current=self.get_task(task['id']);current['provider']=provider;self.store.put('tasks',current['id'],current)
            task['provider']=provider
