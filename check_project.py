"""Run this project's full unittest suite and the V2 audit linkage from the root."""
import sys
import tempfile
import unittest
from pathlib import Path


def run_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return successful


def check_v2_linkage():
    """Freeze, receive, reopen, and export/verify by the original account number."""
    from examples.v2_audit import run

    with tempfile.TemporaryDirectory() as directory:
        try:
            result = run(Path(directory))
        except (AssertionError, ValueError) as exc:
            print(f'V2 LINKAGE FAIL {exc}')
            return False
    expected = {
        'swapped_first_parcel': 'EVIDENCE_MISMATCH',
        'first_receipt': [9],
        'source_pending_after_first': [5, 12],
    }
    for field, value in expected.items():
        if result.get(field) != value:
            print(f'V2 LINKAGE FAIL {field}={result.get(field)!r}, expected {value!r}')
            return False
    detail = result['detail_audit'][0]
    observation = detail['observations'][0]
    checks = (
        detail['ordinal'] == 2,
        (observation['source'], observation['batch_id'], observation['position'])
        == ('gate/b-old', 'audit-morning', 2),
        result['measure_audit'] == [{'ordinal': 2, 'group_id': 9, 'measure': {
            'count': 1, 'total_liters': '7', 'minimum_liters': '7', 'maximum_liters': '7'}}],
        result['empty_group_audit'] == [{'ordinal': 3, 'group_id': 12, 'measure': {
            'count': 0, 'total_liters': '0', 'minimum_liters': None, 'maximum_liters': None}}],
    )
    if not all(checks):
        print('V2 LINKAGE FAIL audit material differs from the frozen facts')
        return False
    print('V2 LINKAGE PASS swapped first parcel rejected; detached anchor verified '
          'group 9 at ordinal 2 and empty group 12 at ordinal 3')
    return True


def main():
    suite_ok = run_suite()
    linkage_ok = check_v2_linkage()
    return 0 if suite_ok and linkage_ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
