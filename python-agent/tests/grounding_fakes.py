"""Stub only the new external auditor in older routing/lifecycle test suites.

The production review contract and real final gate have dedicated coverage in
test_grounding.py. These suites continue to measure their original boundaries.
"""
from unittest.mock import AsyncMock, patch


def setUpModule():
    global auditor, repairer
    auditor = patch('app.services.grounding.review_text', AsyncMock(return_value=[]))
    repairer = patch('app.services.grounding.repair_text', AsyncMock(side_effect=TimeoutError('offline auditor')))
    auditor.start()
    repairer.start()


def tearDownModule():
    repairer.stop()
    auditor.stop()
