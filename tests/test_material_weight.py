"""Gross material weight: which units count and how they convert to kg,
split-bill shares, and the SQL expression agreeing with the Python rule."""

import sqlite3
import unittest

from helpers.material_weight import (
    kg_factor, kg_factor_sql, alloc_kg_sql, bill_kg, export_bill_kg,
)

# unit as a bill might spell it -> kg per unit
WEIGHT_SPELLINGS = {
    'KG': 1, 'kg': 1, 'Kgs': 1, 'KGS.': 1, ' kg ': 1, 'KGM': 1, 'Kilogram': 1,
    'K.G.': 1, 'KG(S)': 1, 'Kilo': 1,
    'MT': 1000, 'M.T.': 1000, 'mts': 1000, 'Ton': 1000, 'TONS': 1000,
    'Tonne': 1000, 'Metric Ton': 1000, 'TNE': 1000,
    'QTL': 100, 'Quintal': 100,
    'G': 0.001, 'gm': 0.001, 'GMS': 0.001, 'Grams': 0.001,
}
NOT_WEIGHT = ['', None, 'NOS', 'PCS', 'LTR', 'MTR', 'METER', 'SQM', 'BAG',
              'KL', 'KGMM', 'NO', 'SET', 'RMT']


class UnitRuleTest(unittest.TestCase):
    def test_weight_units_convert(self):
        for u, factor in WEIGHT_SPELLINGS.items():
            self.assertEqual(kg_factor(u), factor, u)

    def test_other_units_do_not_count(self):
        for u in NOT_WEIGHT:
            self.assertIsNone(kg_factor(u), u)

    def test_sql_matches_python(self):
        # SQLite has the same UPPER / REPLACE / COALESCE / CASE semantics the
        # expression relies on, so the two rules can be compared directly.
        con = sqlite3.connect(':memory:')
        sql = f"SELECT {kg_factor_sql(':u')}"
        for u in list(WEIGHT_SPELLINGS) + NOT_WEIGHT:
            got = con.execute(sql, {'u': u}).fetchone()[0]
            self.assertEqual(got, kg_factor(u), repr(u))


class BillKgTest(unittest.TestCase):
    ITEMS = [
        {'quantity': 1250.5, 'uom': 'KGS'},
        {'quantity': 2, 'uom': 'MT'},        # 2000 kg
        {'quantity': 3, 'uom': 'QTL'},       # 300 kg
        {'quantity': 500, 'uom': 'GMS'},     # 0.5 kg
        {'quantity': 12, 'uom': 'NOS'},      # pieces — not weight
        {'quantity': 40, 'uom': 'MTR'},      # metres — not weight
        {'quantity': None, 'uom': 'KG'},
    ]
    TOTAL = 1250.5 + 2000 + 300 + 0.5

    def test_sums_weight_units_in_kg(self):
        self.assertAlmostEqual(bill_kg(self.ITEMS), self.TOTAL)

    def test_unsplit_bill_takes_full_weight(self):
        # share_ratio of an unsplit bill can drift off 1.0 by rounding.
        bill = {'line_items': self.ITEMS, 'allocation_count': 1, 'share_ratio': 0.9999}
        self.assertAlmostEqual(export_bill_kg(bill), self.TOTAL)

    def test_split_bill_takes_its_share(self):
        bill = {'line_items': self.ITEMS, 'allocation_count': 2, 'share_ratio': 0.4}
        self.assertAlmostEqual(export_bill_kg(bill), self.TOTAL * 0.4)


class AllocKgSqlTest(unittest.TestCase):
    """alloc_kg_sql as the registry / project-summary / card queries use it."""

    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.executescript("""
            CREATE TABLE bill_invoices (id INTEGER, total_amount REAL);
            CREATE TABLE bill_line_items (invoice_id INTEGER, quantity REAL, uom TEXT);
            CREATE TABLE bill_project_allocations (invoice_id INTEGER, project TEXT,
                                                   alloc_total REAL);
            -- bill 1: unsplit, 1000 kg + 1.5 MT + 50 NOS; alloc a paisa off the total
            INSERT INTO bill_invoices VALUES (1, 1000.00);
            INSERT INTO bill_line_items VALUES (1, 1000, 'KGS'), (1, 1.5, 'MT'), (1, 50, 'NOS');
            INSERT INTO bill_project_allocations VALUES (1, '7 - A', 999.99);
            -- bill 2: 3000 kg split 25/75 between two projects
            INSERT INTO bill_invoices VALUES (2, 400.00);
            INSERT INTO bill_line_items VALUES (2, 3000, 'Kg.');
            INSERT INTO bill_project_allocations VALUES (2, '7 - A', 100), (2, '9 - B', 300);
            -- bill 3: no line items at all
            INSERT INTO bill_invoices VALUES (3, 50.00);
            INSERT INTO bill_project_allocations VALUES (3, '7 - A', 50);
        """)

    def total(self, project):
        return self.con.execute(
            f"SELECT COALESCE(SUM({alloc_kg_sql('b', 'a')}), 0) "
            "FROM bill_project_allocations a JOIN bill_invoices b ON b.id = a.invoice_id "
            "WHERE a.project = ?", (project,)).fetchone()[0]

    def test_project_totals(self):
        self.assertAlmostEqual(self.total('7 - A'), 1000 + 1500 + 750)
        self.assertAlmostEqual(self.total('9 - B'), 2250)


if __name__ == '__main__':
    unittest.main()
