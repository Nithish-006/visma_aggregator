"""Gross material weight of purchase bills — every weight-unit line item,
converted to kilograms and summed.

One rule, used by every view and export that reports tonnage, so the Excel
sheets and the screens can't disagree:

* A line item counts when its unit of measure is a unit of weight, however the
  bill spelled it, and is converted to kg by WEIGHT_UNITS below:
    kilograms  KG, KGS, KGM (GST code), KILOGRAM(S), KILO(S)      x 1
    tonnes     MT, MTS (GST code), TON(S), TONNE(S), TNE          x 1000
    quintals   QTL (GST code), QUINTAL(S)                         x 100
    grams      G, GM, GMS (GST code), GRM, GRAM(S)                x 0.001
  Matching ignores case, spaces, dots, hyphens, slashes and brackets.
  Anything else (NOS, PCS, LTR, MTR = metres, SQM, blank, ...) is not a weight
  and is left out.
* A bill split across projects contributes its project's SHARE of the weight,
  in the same proportion as its money (alloc_total / bill total), so a
  project's tonnage reconciles with its share of the bill just as its rupees do.
  Line-item quantities in the DB are always the physical, whole-bill values.
"""

_KG = ('KG', 'KGS', 'KGM', 'KILO', 'KILOS',
       'KILOGRAM', 'KILOGRAMS', 'KILOGRAMME', 'KILOGRAMMES')
_TONNE = ('MT', 'MTS', 'MTON', 'MTONS', 'TON', 'TONS', 'TONNE', 'TONNES', 'TNE',
          'METRICTON', 'METRICTONS', 'METRICTONNE', 'METRICTONNES')
_QUINTAL = ('QTL', 'QTLS', 'QUINTAL', 'QUINTALS')
_GRAM = ('G', 'GM', 'GMS', 'GRM', 'GRMS', 'GRAM', 'GRAMS', 'GRAMME', 'GRAMMES')

# Normalised unit -> kilograms per unit.
WEIGHT_UNITS = {
    **{u: 1.0 for u in _KG},
    **{u: 1000.0 for u in _TONNE},
    **{u: 100.0 for u in _QUINTAL},
    **{u: 0.001 for u in _GRAM},
}

# Characters dropped before comparing a unit. The SQL expression below strips
# exactly the same set, so Python and MySQL classify every unit identically.
_STRIP_CHARS = ('.', ' ', '(', ')', '-', '/')


def normalize_unit(uom):
    s = str(uom or '').upper()
    for ch in _STRIP_CHARS:
        s = s.replace(ch, '')
    return s


def kg_factor(uom):
    """Kilograms per unit of `uom`, or None when it isn't a weight unit."""
    return WEIGHT_UNITS.get(normalize_unit(uom))


def is_weight_unit(uom):
    return kg_factor(uom) is not None


def kg_factor_sql(col):
    """SQL scalar: kilograms per unit of `col` (a uom column), NULL if not a weight."""
    expr = f"UPPER(COALESCE({col}, ''))"
    for ch in _STRIP_CHARS:
        expr = f"REPLACE({expr}, '{ch}', '')"
    by_factor = {}
    for unit, factor in WEIGHT_UNITS.items():
        by_factor.setdefault(factor, []).append(unit)
    whens = ' '.join(
        f"WHEN {expr} IN ({', '.join(repr(u) for u in sorted(units))}) THEN {factor!r}"
        for factor, units in by_factor.items())
    return f"(CASE {whens} ELSE NULL END)"


def bill_kg_sql(invoice_id_expr, items_table='bill_line_items'):
    """SQL scalar: the whole bill's weight in kg (0 when it has none)."""
    return (f"(SELECT COALESCE(SUM(kgli.quantity * {kg_factor_sql('kgli.uom')}), 0) "
            f"FROM {items_table} kgli WHERE kgli.invoice_id = {invoice_id_expr})")


def alloc_kg_sql(bill_alias='b', alloc_alias='a'):
    """SQL scalar: this allocation's share of the bill's weight in kg.

    An unsplit bill takes its full weight (ratio exactly 1, not alloc/total,
    which can drift by a paisa of rounding); a split bill takes the money share.
    """
    b, a = bill_alias, alloc_alias
    ratio = (f"(CASE WHEN (SELECT COUNT(*) FROM bill_project_allocations kga "
             f"WHERE kga.invoice_id = {b}.id) > 1 AND {b}.total_amount > 0 "
             f"THEN {a}.alloc_total / {b}.total_amount ELSE 1 END)")
    return f"({bill_kg_sql(f'{b}.id')} * {ratio})"


def bill_kg(line_items, ratio=1.0):
    """Python twin of alloc_kg_sql for already-fetched line items."""
    total = 0.0
    for item in line_items or []:
        factor = kg_factor(item.get('uom'))
        if factor is None:
            continue
        try:
            total += float(item.get('quantity') or 0) * factor
        except (TypeError, ValueError):
            pass
    return total * (ratio if ratio is not None else 1.0)


def export_bill_kg(bill):
    """Weight share (kg) of one entry from get_bills_with_line_items_for_export()."""
    split = int(bill.get('allocation_count', 1) or 1) > 1
    ratio = float(bill.get('share_ratio', 1.0) or 0) if split else 1.0
    return bill_kg(bill.get('line_items'), ratio)


# The sentence printed under every weight total, so a reader knows what's in it.
WEIGHT_NOTE = ('Weight-unit line items converted to kg: KG, MT/TON (x1000), '
               'QTL (x100), GMS (x0.001). Non-weight units (NOS, PCS, LTR, MTR ...) '
               'are not included.')
