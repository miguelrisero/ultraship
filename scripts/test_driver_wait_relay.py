"""Exercise terminal wait delivery and acknowledgment at the chief's relay boundary."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock


RELAY = (Path(__file__).resolve().parents[1] / 'plugins/ship/skills/ship/scripts/driver-wait-relay.py')


class DriverWaitRelayTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(RELAY.is_file(), 'Ship driver wait terminal relay callback is missing')
        spec = importlib.util.spec_from_file_location('driver_wait_relay', RELAY)
        self.relay = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.relay)
        self.wait = {
            'session_id': '00000000-0000-4000-8000-000000000001',
            'lane': 'lane-one',
            'driver_id': 'driver-one',
            'task_id': 'bciwait01',
            'pr_url': 'https://github.com/example/repo/pull/17',
            'head_sha': 'a' * 40,
            'stage': 'ci',
            'deadline': '2026-11-20T19:35:00Z',
        }
        self.result = {**self.wait, 'receipt_id': 'result-one', 'outcome': 'success'}
        self.native_send = Mock(return_value=True)

    def deliver(self, **fields):
        # Invoke the callback with the event that the chief's terminal channel would deliver.
        return self.relay.on_terminal_result(
            self.wait, {**self.result, **fields}, send_to_driver=self.native_send,
        )

    def acknowledge(self, forwarded, acknowledgment, *, sender='driver-one'):
        return self.relay.acknowledge_terminal_result(
            self.wait, forwarded, acknowledgment, sender_agent_id=sender,
        )

    def test_success_requires_original_driver_acknowledgment_and_fresh_verification(self):
        forwarded = self.deliver()
        self.native_send.assert_called_once_with('driver-one', self.result)
        self.assertEqual(forwarded, self.result)
        self.assertEqual(self.acknowledge(forwarded, None), 'hold')
        self.assertEqual(self.acknowledge(forwarded, dict(self.result)), 'verify')

    def test_failure_and_timeout_reach_the_original_driver_and_keep_the_gate_closed(self):
        for outcome in ('failure', 'timeout'):
            with self.subTest(outcome=outcome):
                self.native_send.reset_mock()
                receipt = {**self.result, 'outcome': outcome}
                forwarded = self.deliver(outcome=outcome)
                self.native_send.assert_called_once_with('driver-one', receipt)
                self.assertEqual(forwarded, receipt)
                self.assertEqual(self.acknowledge(forwarded, dict(receipt)), 'hold')

    def test_terminal_result_for_another_wait_does_not_reach_the_driver(self):
        for field, value in {
            'session_id': '00000000-0000-4000-8000-000000000002',
            'lane': 'lane-two',
            'driver_id': 'driver-two',
            'task_id': 'bciwait02',
            'pr_url': 'https://github.com/example/repo/pull/18',
            'head_sha': 'b' * 40,
            'stage': 'review',
            'deadline': '2026-11-20T19:40:00Z',
        }.items():
            with self.subTest(field=field):
                forwarded = self.deliver(**{field: value})
                self.native_send.assert_not_called()
                self.assertIsNone(forwarded)
                self.assertEqual(self.acknowledge(forwarded, {**self.result, field: value}), 'hold')

    def test_failed_native_delivery_keeps_the_gate_closed(self):
        self.native_send.return_value = False
        forwarded = self.deliver()
        self.assertIsNone(forwarded)
        self.assertEqual(self.acknowledge(forwarded, dict(self.result)), 'hold')

    def test_another_driver_cannot_acknowledge_the_receipt(self):
        receipt = self.deliver()
        self.assertEqual(self.acknowledge(receipt, dict(self.result), sender='driver-two'), 'hold')

    def test_original_driver_cannot_acknowledge_a_different_receipt(self):
        receipt = self.deliver()
        for fields in ({'receipt_id': 'result-two'}, {'task_id': 'bciwait02'}, {'outcome': 'timeout'}):
            with self.subTest(fields=fields):
                self.assertEqual(self.acknowledge(receipt, {**receipt, **fields}), 'hold')


if __name__ == '__main__':
    unittest.main()
