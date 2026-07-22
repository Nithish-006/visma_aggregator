"""Unit tests for the pure bill-split math (no DB)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.bill_split import (
    apportion, compute_split_allocations, validate_split_targets,
)


def _cents(x):
    return int(round(x * 100))


def test_apportion_sums_exactly_even():
    parts = apportion(100.00, [1, 1, 1])
    assert _cents(sum(parts)) == _cents(100.00)
    # 100.00 / 3 -> 33.34, 33.33, 33.33 (largest remainder gets the extra paisa)
    assert sorted(parts) == [33.33, 33.33, 33.34]


def test_apportion_proportional():
    parts = apportion(100.00, [60, 40])
    assert parts == [60.00, 40.00]


def test_apportion_odd_ratio_still_exact():
    parts = apportion(1000.00, [7, 11, 13])
    assert _cents(sum(parts)) == _cents(1000.00)


def test_compute_split_reconciles_every_column():
    bill = {'subtotal': 84745.76, 'total_cgst': 7627.12, 'total_sgst': 7627.12,
            'total_igst': 0.0, 'total_amount': 100000.00}
    targets = [{'project': '659 - JAMUNA', 'amount': 60000.00},
               {'project': '712 - KAVERI', 'amount': 40000.00}]
    allocs = compute_split_allocations(bill, targets)

    assert len(allocs) == 2
    for col, billkey in [('alloc_taxable', 'subtotal'), ('alloc_cgst', 'total_cgst'),
                         ('alloc_sgst', 'total_sgst'), ('alloc_igst', 'total_igst'),
                         ('alloc_total', 'total_amount')]:
        s = sum(a[col] for a in allocs)
        assert _cents(s) == _cents(bill[billkey]), f"{col} did not reconcile: {s} vs {bill[billkey]}"


def test_compute_split_three_way_awkward_numbers():
    bill = {'subtotal': 999.99, 'total_cgst': 90.00, 'total_sgst': 90.00,
            'total_igst': 0.0, 'total_amount': 1179.99}
    targets = [{'project': 'A', 'amount': 393.33},
               {'project': 'B', 'amount': 393.33},
               {'project': 'C', 'amount': 393.33}]
    allocs = compute_split_allocations(bill, targets)
    for col, billkey in [('alloc_taxable', 'subtotal'), ('alloc_cgst', 'total_cgst'),
                         ('alloc_sgst', 'total_sgst'), ('alloc_total', 'total_amount')]:
        s = sum(a[col] for a in allocs)
        assert _cents(s) == _cents(bill[billkey]), f"{col}: {s} vs {bill[billkey]}"


def test_validate_rejects_single_target():
    ok, err = validate_split_targets(100.0, [{'project': 'A', 'amount': 100.0}])
    assert not ok and 'at least 2' in err


def test_validate_rejects_mismatched_sum():
    ok, err = validate_split_targets(
        100.0, [{'project': 'A', 'amount': 60.0}, {'project': 'B', 'amount': 30.0}])
    assert not ok and 'add up' in err


def test_validate_rejects_duplicate_project():
    ok, err = validate_split_targets(
        100.0, [{'project': 'A', 'amount': 50.0}, {'project': 'A', 'amount': 50.0}])
    assert not ok and 'more than once' in err


def test_validate_rejects_zero_total_bill():
    ok, err = validate_split_targets(
        0.0, [{'project': 'A', 'amount': 0.0}, {'project': 'B', 'amount': 0.0}])
    assert not ok


def test_validate_accepts_penny_tolerance():
    ok, err = validate_split_targets(
        100.00, [{'project': 'A', 'amount': 60.00}, {'project': 'B', 'amount': 40.005}])
    assert ok, err


if __name__ == '__main__':
    # Allow running without pytest.
    import traceback
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                passed += 1
                print(f"[+] {name}")
            except Exception:
                failed += 1
                print(f"[!] {name} FAILED")
                traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
