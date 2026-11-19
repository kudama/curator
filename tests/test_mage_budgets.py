import copy
import unittest
from unittest.mock import patch
import test_curator


class MageBudgetTests(unittest.TestCase):
    setUp=test_curator.Workflows.setUp
    tearDown=test_curator.Workflows.tearDown

    def quotes(self,count=2):
        tasks=[self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0] for _ in range(count)]
        with patch('curator.mage.Mage') as cls:
            p=cls.return_value;p.credential_identity.return_value='fixture'
            p.quote.return_value={'gems':7,'body':{'prompt':'Synthetic'},'basis':'fixture'}
            receipts=[self.service.mage_quote([dict(id=t['id'],version=t['version'])]) for t in tasks]
        return tasks,receipts

    def approve(self,q):
        with patch('curator.mage.Mage') as cls:
            cls.return_value.credential_identity.return_value='fixture'
            return self.service.authorize_mage(q['id'],True)

    def test_reservations_prevent_two_quotes_overspending_monthly_allowance(self):
        self.service.save_config({'mage_monthly_budget':10})
        tasks,quotes=self.quotes();self.approve(quotes[0])
        with self.assertRaisesRegex(ValueError,'monthly'):self.approve(quotes[1])
        self.assertEqual(self.service.mage_budget_usage()['committed'],7)
        self.assertEqual(self.service.get_task(tasks[1]['id'])['status'],'recommendation')

    def test_unsubmitted_cancel_releases_but_uncertain_terminal_keeps_reservation(self):
        self.service.save_config({'mage_monthly_budget':10})
        tasks,quotes=self.quotes();self.approve(quotes[0]);t=self.service.get_task(tasks[0]['id'])
        self.service.action(t['id'],'cancel',t['version']);self.assertEqual(self.service.mage_budget_usage()['committed'],0)
        self.approve(quotes[1]);t=self.service.get_task(tasks[1]['id'])
        p=copy.deepcopy(t['provider']);p.update(attempted=True,billing={})
        self.service.reconcile_mage_budget(t['id'],p,terminal=True)
        self.assertEqual(self.service.mage_budget_usage()['committed'],7)

    def test_actual_charge_and_only_confirmed_refunds_adjust_budget(self):
        tasks,quotes=self.quotes(1);self.approve(quotes[0]);t=self.service.get_task(tasks[0]['id'])
        p=copy.deepcopy(t['provider']);p.update(attempted=True,billing={'gems_charged':9})
        self.service.reconcile_mage_budget(t['id'],p,terminal=True)
        self.assertEqual(self.service.mage_budget_usage()['committed'],9)
        p['billing']['gems_refunded']=9;self.service.reconcile_mage_budget(t['id'],p,terminal=True)
        self.assertEqual(self.service.mage_budget_usage()['committed'],0)

    def test_batch_allowance_and_nonfinite_values_are_rejected(self):
        tasks,quotes=self.quotes(1)
        self.service.save_config({'mage_batch_budget':3})
        with patch('curator.mage.Mage') as cls:
            p=cls.return_value;p.credential_identity.return_value='fixture';p.quote.return_value={'gems':7,'body':{},'basis':'fixture'}
            with self.assertRaisesRegex(ValueError,'batch'):self.service.mage_quote([dict(id=tasks[0]['id'],version=1)])
        for value in (True,-1,float('inf'),float('nan'),'10'):
            with self.subTest(value=value),self.assertRaises(ValueError):self.service.save_config({'mage_monthly_budget':value})

    def test_new_month_checks_allowance_before_moving_reservation(self):
        self.service.save_config({'mage_monthly_budget':10})
        with patch.object(self.service,'mage_budget_period',return_value='2026-10'):
            tasks,quotes=self.quotes(1);self.approve(quotes[0])
        t=self.service.get_task(tasks[0]['id']);old=t['provider']['budget_period']
        self.service.ensure_mage_budget_for_submission(t)
        self.assertNotEqual(t['provider']['budget_period'],old)
        self.assertEqual(self.service.mage_budget_usage(old)['committed'],0)
        self.assertEqual(self.service.mage_budget_usage()['committed'],7)

    def test_malformed_refund_never_hides_a_known_charge(self):
        tasks,quotes=self.quotes(1);self.approve(quotes[0]);t=self.service.get_task(tasks[0]['id'])
        provider=dict(t['provider'],attempted=True,billing={'gems_charged':12,'gems_refunded':'unknown'})
        self.service.reconcile_mage_budget(t['id'],provider,terminal=True)
        self.assertEqual(self.service.mage_budget_usage()['committed'],12)

    def test_over_budget_quote_reports_total_count_budget_and_shortfall_without_reserving(self):
        tasks=[self.service.artwork_plan([self.asset['id']],'cover','gritty')['tasks'][0] for _ in range(2)]
        with patch('curator.mage.Mage') as cls:
            p=cls.return_value;p.credential_identity.return_value='fixture';p.quote.return_value={'gems':135,'body':{},'basis':'fixture'}
            with self.assertRaisesRegex(ValueError,r'Estimated cost: 270 Gems for 2 options.*batch budget: 200 Gems.*70 Gems over budget'):
                self.service.mage_quote([{'id':t['id'],'version':t['version']} for t in tasks],batch_limit=200)
            p.submit.assert_not_called()
        self.assertEqual(self.service.mage_budget_usage()['committed'],0)
        self.assertTrue(all(self.service.get_task(t['id'])['status']=='recommendation' for t in tasks))

    def test_monthly_budget_failure_reports_quote_and_remaining_allowance(self):
        self.service.save_config({'mage_monthly_budget':10})
        tasks,quotes=self.quotes();self.approve(quotes[0])
        with self.assertRaisesRegex(ValueError,r'Estimated cost: 7 Gems for 1 option.*monthly allowance: 3 Gems.*4 Gems over budget'):
            self.approve(quotes[1])
        self.assertEqual(self.service.mage_budget_usage()['committed'],7)
        self.assertEqual(self.service.get_task(tasks[1]['id'])['status'],'recommendation')
