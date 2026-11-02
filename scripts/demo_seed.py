"""
Made-up but internally consistent business data for the demo database.

One fictional steel-fabrication firm, eight projects, April 2026 to today. The
figures are generated as events, not as independent piles, so every screen
agrees with every other one:

  * each project has a PO; sales invoices bill it in stages; client receipts
    (KVB credits tagged "<id> - NAME") follow those invoices;
  * purchase bills are raised against projects and paid from KVB a few weeks
    later - most in full, a few still outstanding, one advance with no bill yet,
    so the material reconciliation has something to show;
  * site spend, transport, crane hire and labour go out of Axis, tagged to the
    project they were for; salaries, rent, power and office spend are untagged;
  * GST is paid each month on the previous month's output less input;
  * Axis is topped up from KVB whenever it runs low, so neither running balance
    ever goes negative;
  * the last few weeks hold a batch of rows the category memory was unsure of
    ('suggested'), so the dashboard's "Needs review" filter is not empty.

Everything is drawn from random.Random(SEED): re-running gives the same data.
No name, GSTIN or amount here belongs to a real business.
"""

import json
import random
from datetime import date, datetime, time, timedelta

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from extraction_validator import validate_db_row, notes_from_result  # noqa: E402

SEED = 20261102
START = date(2026, 4, 1)

COMPANY = {
    'name': 'KAVERI STEEL STRUCTURES',
    'gstin': '33AAKFK4821M1Z5',
    'address': 'SF 112, SIDCO Industrial Estate, Coimbatore - 641021',
    'state': 'Tamil Nadu',
}
STATE_NAMES = {'33': 'Tamil Nadu', '32': 'Kerala', '29': 'Karnataka'}

CATEGORIES = [
    ('OFFICE EXPENSES', 'OE'), ('FACTORY EXPENSES', 'FE'), ('SITE EXPENSES', 'SE'),
    ('TRANSPORT EXPENSES', 'TE'), ('MATERIAL PURCHASE', 'MP'), ('DUTIES & TAX', 'DT'),
    ('SALARY AC', 'SA'), ('BANK CHARGES', 'BC'), ('AMOUNT RECEIVED', 'AR'),
    ('UNCATEGORIZED', 'UC'),
]
# Categories users type that no keyword list holds - the demo should show them.
EXTRA_CODES = {'CRANE RENT': 'CR', 'LABOUR PAYMENT': 'LP', 'AMOUNT TRANSFER': 'AT',
               'EB BILL': 'EB', 'TRAVELLING EXPENSES': 'TR', 'CAPITAL AC': 'CA',
               'PETTY CASH': 'PC', 'CONTRACT PAYMENT': 'CP'}
CODE = dict(CATEGORIES, **EXTRA_CODES)

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

PO_ITEMS = {  # key: (description, unit, rate, HSN/SAC)
    'steel':   ('Supply & fabrication of structural steel (PEB frames)', 'MT', 96_500, '7308'),
    'erect':   ('Erection of structural steel at site', 'MT', 9_800, '995468'),
    'roof':    ('Supply & fixing of 0.47mm colour-coated roofing sheet', 'SQM', 645, '7210'),
    'sky':     ('Polycarbonate skylight sheet with fixing', 'SQM', 1_480, '3920'),
    'gutter':  ('GI gutter with downtake pipe', 'RMT', 790, '7308'),
    'paint':   ('Primer + two coats synthetic enamel', 'SQM', 96, '995472'),
    'anchor':  ('Anchor bolts & base plates', 'SET', 3_250, '7318'),
    'deck':    ('Mezzanine floor deck sheet with shear studs', 'SQM', 1_870, '7308'),
    'canopy':  ('Entrance canopy - fabrication & erection', 'SQM', 4_200, '7308'),
    'design':  ('Structural design, detailing & shop drawings', 'LS', 1, '998331'),
}

PAYMENT_TERMS = ('20% advance with PO, 70% pro-rata against supply on submission of '
                 'invoice, 10% on completion of erection. Payment within 15 days.')

# status drives dates and how far billing/receipts have got.
PROJECTS = [
    dict(id=701, stem='AURA TEXTILES', client='AURA TEXTILE MILLS PVT LTD', state='33',
         lines=[('steel', 42), ('erect', 42), ('roof', 3_600), ('gutter', 240),
                ('paint', 3_100), ('anchor', 64)],
         start=date(2026, 4, 6), end=date(2026, 7, 28), billed=1.0, received=0.95,
         material=0.7, overhead=150_000,
         actuals={'steel': 40.6, 'erect': 40.6, 'roof': 3_540}),
    dict(id=702, stem='GREENFIELD SCHOOL', client='GREENFIELD EDUCATIONAL TRUST', state='33',
         lines=[('steel', 24), ('erect', 24), ('roof', 2_200), ('sky', 180),
                ('gutter', 160), ('paint', 1_900)],
         start=date(2026, 6, 2), end=None, billed=0.72, received=0.6, material=0.55,
         overhead=60_000,
         variations=[('Additional entrance canopy as per revised drawing', 'canopy', 48,
                      date(2026, 8, 18)),
                     ('Extra skylight panels over corridor', 'sky', 60, date(2026, 9, 9))],
         third_party_in=[('GREENFIELD PARENTS ASSOCIATION', 'Contribution towards roofing, '
                          'paid directly by cheque', 200_000, date(2026, 9, 26))]),
    dict(id=703, stem='LAKEVIEW RESIDENCY', client='LAKEVIEW HOMES LLP', state='33',
         lines=[('roof', 1_350), ('gutter', 220), ('sky', 40), ('paint', 600)],
         start=date(2026, 5, 11), end=date(2026, 8, 30), billed=0.92, received=0.8,
         material=0.68, overhead=25_000,
         cash=[(150_000, date(2026, 7, 14), 'Cash handed over at site by Mr. Rajan')]),
    dict(id=704, stem='SUNRISE FOODS', client='SUNRISE AGRO FOODS PVT LTD', state='33',
         lines=[('steel', 28), ('erect', 28), ('roof', 2_400), ('gutter', 180),
                ('paint', 2_000), ('anchor', 40)],
         start=date(2026, 7, 6), end=None, billed=0.58, received=0.52, material=0.5,
         overhead=0,
         third_party_out=[('SURESH CIVIL WORKS', 'Foundation & plinth beam (client scope)',
                           650_000, date(2026, 8, 21))]),
    dict(id=705, stem='METRO WAREHOUSE', client='METRO LOGISTICS PARK PVT LTD', state='29',
         lines=[('steel', 65), ('erect', 65), ('roof', 5_800), ('sky', 420),
                ('gutter', 380), ('paint', 4_700), ('anchor', 96), ('deck', 520)],
         start=date(2026, 9, 3), end=None, billed=0.22, received=0.3, material=0.32,
         overhead=0),
    dict(id=706, stem='SRI MURUGAN TEMPLE', client='SRI MURUGAN TEMPLE TRUST', state='33',
         lines=[('canopy', 120), ('paint', 380)],
         start=date(2026, 4, 14), end=date(2026, 6, 10), billed=1.0, received=1.0,
         material=0.68, overhead=15_000, inactive=True),
    dict(id=707, stem='NOVA SHOWROOM', client='NOVA MOTORS', state='33', ptype='design',
         lines=[('design', 285_000)],
         start=date(2026, 8, 4), end=date(2026, 9, 20), billed=1.0, received=1.0,
         material=0.0, overhead=0),
    dict(id=708, stem='RIVERSIDE CLINIC', client='RIVERSIDE HEALTHCARE', state='33',
         lines=[('steel', 14), ('erect', 14), ('roof', 1_100), ('paint', 900)],
         start=date(2026, 10, 7), end=None, billed=0.0, received=0.15, material=0.12,
         overhead=0),
]


def display(p):
    return f"{p['id']} - {p['stem']}"


# ---------------------------------------------------------------------------
# Vendors and catalogues
# ---------------------------------------------------------------------------

MATERIAL_VENDORS = {  # name: (state, PAN stem, [(item, HSN, unit, rate)])
    'ANAND STEEL TRADERS': ('33', 'AANFA', [
        ('ISMB 200 beam', '7216', 'KG', 61.5), ('ISMC 150 channel', '7216', 'KG', 60.2),
        ('MS angle 65x65x6', '7216', 'KG', 59.8), ('MS plate 10mm', '7208', 'KG', 63.4)]),
    'SRI BALAJI STEELS': ('33', 'ABDFS', [
        ('Z purlin 200x60x2.0', '7216', 'KG', 72.0), ('MS pipe 50NB medium', '7306', 'KG', 76.5),
        ('MS flat 50x6', '7216', 'KG', 60.9)]),
    'VINAYAKA ROOFING PRODUCTS': ('33', 'AAKFV', [
        ('Colour-coated sheet 0.47mm', '7210', 'SQM', 512), ('Ridge cap 0.47mm', '7210', 'RMT', 268),
        ('Polycarbonate sheet 2mm', '3920', 'SQM', 1_140), ('GI gutter 0.8mm', '7308', 'RMT', 455)]),
    'PRECISION FASTENERS': ('33', 'AAPFP', [
        ('Self-drilling screw 5.5x25', '7318', 'BOX', 1_450), ('Anchor bolt M20x600', '7318', 'NOS', 146),
        ('HSFG bolt M16x60', '7318', 'NOS', 38)]),
    'MEGA PAINTS DEPOT': ('33', 'AAMFM', [
        ('Red oxide primer 20L', '3208', 'NOS', 3_850), ('Synthetic enamel 20L', '3208', 'NOS', 6_200),
        ('Thinner 5L', '3814', 'NOS', 820)]),
    'SRI SAKTHI GASES': ('33', 'ABSFS', [
        ('Oxygen cylinder refill', '2804', 'NOS', 420), ('Welding electrode 3.15mm', '8311', 'PKT', 985),
        ('Grinding disc 4in', '6804', 'NOS', 46)]),
    'MALABAR ALLOYS': ('32', 'AAMCM', [  # out of state: IGST
        ('MS plate 12mm', '7208', 'KG', 62.1), ('MS chequered plate 6mm', '7208', 'KG', 66.0)]),
}
# Which vendors a project buys from, in order of phase (steel first, finish last).
VENDOR_PHASES = [
    (0.0, ['ANAND STEEL TRADERS', 'SRI BALAJI STEELS', 'MALABAR ALLOYS', 'PRECISION FASTENERS']),
    (0.35, ['SRI BALAJI STEELS', 'ANAND STEEL TRADERS', 'SRI SAKTHI GASES']),
    (0.6, ['VINAYAKA ROOFING PRODUCTS', 'PRECISION FASTENERS']),
    (0.8, ['MEGA PAINTS DEPOT', 'VINAYAKA ROOFING PRODUCTS']),
]
VENDOR_BANKS = {'ANAND STEEL TRADERS': 'HDFC', 'SRI BALAJI STEELS': 'CNRB',
                'VINAYAKA ROOFING PRODUCTS': 'SBIN', 'PRECISION FASTENERS': 'IOBA',
                'MEGA PAINTS DEPOT': 'UBIN', 'SRI SAKTHI GASES': 'KVBL',
                'MALABAR ALLOYS': 'FDRL'}

# (category, payees, remark, amount range, bank, share of project spend)
PROJECT_SPEND = [
    ('TRANSPORT EXPENSES', ['VELU TRANSPORTS', 'KANNAN LORRY SERVICE'], 'lorry', (4_500, 16_000)),
    ('CRANE RENT', ['SRI AMMAN CRANES'], 'crane', (9_000, 38_000)),
    ('SITE EXPENSES', ['RAVI KUMAR S', 'SELVAM K'], 'site exp', (2_000, 14_000)),
    ('LABOUR PAYMENT', ['MURUGAN P', 'THANGARAJ M'], 'labour', (18_000, 55_000)),
]
SPEND_WEIGHTS = [3, 1, 5, 3]

STAFF = [('KARTHIK V', 32_000), ('PRIYA S', 26_500), ('MANOJ R', 22_000),
         ('DEEPA L', 18_500), ('ARUL S', 28_000)]
BANKS = ['SBIN', 'CNRB', 'IOBA', 'HDFC', 'ICIC', 'UBIN', 'KVBL']
BANK_NAMES = {'SBIN': 'State Bank Of India', 'CNRB': 'CANARA BANK', 'IOBA': 'Indian Overseas Bank',
              'HDFC': 'HDFC BANK', 'ICIC': 'ICICI Bank', 'UBIN': 'Union Bank of India',
              'KVBL': 'Karur Vysya Bank', 'FDRL': 'Federal Bank'}


class Gen:
    def __init__(self, today):
        self.rng = random.Random(SEED)
        self.today = today
        self.kvb, self.axis = [], []
        self.bills, self.sales = [], []          # (header dict, [line dicts], [allocations])
        self.po, self.ledgers = [], []
        self.cash, self.third_party, self.personal = [], [], []
        self._refs = set()

    # -- helpers -----------------------------------------------------------
    def ref(self, digits=12):
        while True:
            r = str(self.rng.randint(10 ** (digits - 1), 10 ** digits - 1))
            if r not in self._refs:
                self._refs.add(r)
                return r

    def at(self, d, lo=9, hi=19):
        return datetime.combine(d, time(self.rng.randint(lo, hi - 1), self.rng.randint(0, 59),
                                        self.rng.randint(0, 59)))

    def clamp(self, d):
        return min(d, self.today)

    def gstin(self, state, pan_stem):
        return f"{state}{pan_stem}{self.rng.randint(1000, 9999)}{chr(65 + self.rng.randint(0, 25))}1Z{self.rng.randint(1, 9)}"

    def provenance(self, category, vendor, credit=False):
        if credit:
            return 'credit', 1.0, None
        roll = self.rng.random()
        if roll < 0.62:
            return 'manual', None, None
        if roll < 0.9:
            conf = round(self.rng.uniform(0.82, 0.98), 3)
            share = int(conf * 100) + self.rng.randint(-3, 1)
            return 'learned', conf, (f'"{vendor}": {category} in {share}% of '
                                     f'~{self.rng.randint(8, 46)} past transactions')
        return 'keyword', None, None

    def bank_row(self, bank, when, desc, vendor, category, dr=0.0, cr=0.0, project=None,
                 source=None):
        src, conf, note = source or self.provenance(category, vendor, credit=cr > 0)
        row = [when, desc, vendor, category, CODE.get(category, 'UC'), src, conf, note,
               round(dr, 2), round(cr, 2), project]
        (self.kvb if bank == 'kvb' else self.axis).append(row)
        return row

    # -- narrations ----------------------------------------------------------
    def kvb_dr(self, payee, amount, remark=''):
        bank = VENDOR_BANKS.get(payee) or self.rng.choice(BANKS)
        if amount >= 200_000:
            return f"RTGS DR-KVBLR5{self.ref(10)}-{payee}-{bank}"
        if self.rng.random() < 0.5:
            return f"NEFT DR-KVBLH{self.ref(11)}-{payee}-{bank}"
        return (f"IMPS-{self.ref()}-{payee}-{bank}-xxxxxxxxxxx{self.rng.randint(1000, 9999)}"
                f"-{(remark or 'PAY')[:4].upper()}")

    def kvb_cr(self, payer, amount):
        bank = self.rng.choice(['HDFC', 'ICIC', 'SBIN', 'UTIB'])
        if amount >= 200_000:
            return f"RTGS CR-{bank}0{self.rng.randint(100000, 999999)}-{payer}-{bank}R5{self.ref(10)}"
        return f"NEFT CR-{bank}0{self.rng.randint(100000, 999999)}-{payer}"

    def axis_dr(self, payee, remark, amount):
        bank = BANK_NAMES[self.rng.choice(BANKS)]
        if amount > 50_000 or self.rng.random() < 0.25:
            return f"INB/NEFT/AXOIC{self.ref(9)}/{payee}/{bank}/"
        return f"UPI/P2A/{self.ref()}/{payee:<20}/{remark}/{bank}"

    def axis_merchant(self, merchant, amount):
        return f"UPI/P2M/{self.ref()}/{merchant:<20}/UPI/{BANK_NAMES[self.rng.choice(BANKS)]}"

    # -- projects ------------------------------------------------------------
    def build_projects(self):
        for p in PROJECTS:
            self.project(p)

    def project(self, p):
        rng = self.rng
        disp = display(p)
        lines = []
        for key, qty in p['lines']:
            desc, unit, rate, hsn = PO_ITEMS[key]
            if key == 'design':
                qty, rate = 1, qty
            lines.append({'key': key, 'description': desc, 'quantity': qty, 'unit': unit,
                          'rate': rate, 'amount': round(qty * rate, 2), 'hsn': hsn})
        taxable = sum(l['amount'] for l in lines)
        tax = round(taxable * 0.18, 2)
        p['contract_basic'], p['contract_total'] = taxable, taxable + tax
        self.po.append({
            'project_id': p['id'], 'po_number': f"{p['client'].split()[0][:4]}/PO/{p['id']}/26-27",
            'po_date': p['start'] - timedelta(days=rng.randint(3, 12)), 'client_name': p['client'],
            'taxable_value': taxable, 'total_tax': tax, 'total_value': taxable + tax,
            'line_items': [{k: l[k] for k in ('description', 'quantity', 'unit', 'rate', 'amount')}
                           for l in lines],
        })

        end = p['end'] or self.today
        span = max((end - p['start']).days, 20)

        # Variations / actuals (ledger rows priced at 18%).
        for desc, key, qty, when in p.get('variations', []):
            rate = PO_ITEMS[key][2]
            basic = round(qty * rate, 2)
            self.ledgers.append(('variation', p['id'], desc, qty, PO_ITEMS[key][1], rate, basic, when))
        for key, qty in (p.get('actuals') or {}).items():
            desc, unit, rate, _ = PO_ITEMS[key]
            self.ledgers.append(('actual', p['id'], desc + ' (as measured)', qty, unit, rate,
                                 round(qty * rate, 2), p['end']))
        if p.get('actuals'):  # unmeasured lines carry over at PO quantity
            for l in lines:
                if l['key'] not in p['actuals']:
                    self.ledgers.append(('actual', p['id'], l['description'], l['quantity'],
                                         l['unit'], l['rate'], l['amount'], p['end']))

        # Sales invoices in stages.
        invoices = []
        if p['billed'] > 0:
            n = 1 if p.get('ptype') == 'design' else max(1, round(p['billed'] * 5))
            weights = [rng.uniform(0.7, 1.3) for _ in range(n)]
            fracs = [p['billed'] * w / sum(weights) for w in weights]
            for i, f in enumerate(fracs):
                when = p['start'] + timedelta(days=int(span * (i + 1) / (n + 0.6)))
                when = self.clamp(when - timedelta(days=rng.randint(0, 4)))
                items = [dict(l, quantity=round(l['quantity'] * f, 3),
                              amount=round(l['quantity'] * f * l['rate'], 2)) for l in lines]
                invoices.append(self.sales_invoice(p, when, items))

        # Client receipts: an advance, then each invoice settled 10-35 days on,
        # until the project's received share is reached.
        # Paid in full means to the rupee; part-paid amounts are round figures.
        target = (round(p['contract_total']) if p['received'] >= 1
                  else round(p['contract_total'] * p['received'], -3))
        paid = 0.0
        receipts = []
        adv = min(target, round(p['contract_total'] * (0.2 if p.get('ptype') != 'design' else 0.4), -3))
        if adv:
            receipts.append((p['start'] + timedelta(days=rng.randint(1, 4)), adv))
            paid += adv
        for inv_date, inv_total in invoices:
            if paid >= target:
                break
            when = inv_date + timedelta(days=rng.randint(10, 35))
            if when > self.today:
                continue
            amt = min(target - paid, round(inv_total * 0.8, -3))
            if amt > 0:
                receipts.append((when, amt))
                paid += amt
        if target - paid >= 1_000 and receipts:  # settle the rest on the last receipt
            when, amt = receipts[-1]
            receipts[-1] = (when, amt + target - paid)
        for when, amt in receipts:
            self.bank_row('kvb', self.at(when, 10, 17), self.kvb_cr(p['client'][:32], amt),
                          p['client'], 'AMOUNT RECEIVED', cr=amt, project=disp)

        for amt, when, note in p.get('cash', []):
            self.cash.append((p['id'], amt, when, note))
        for payee, purpose, amt, when in p.get('third_party_out', []):
            # The client sends the civil contractor's share through us...
            self.bank_row('kvb', self.at(when - timedelta(days=3), 11, 16),
                          self.kvb_cr(p['client'][:32], amt), p['client'], 'AMOUNT RECEIVED',
                          cr=amt, project=disp)
            # ...and it leaves again untagged: it is not this project's cost.
            self.bank_row('kvb', self.at(when, 11, 17), self.kvb_dr(payee, amt), payee,
                          'CONTRACT PAYMENT', dr=amt, source=('manual', None, None))
            self.third_party.append((p['id'], 'out', payee, purpose, amt, when,
                                     'Client-scope civil work routed through us'))
        for payee, purpose, amt, when in p.get('third_party_in', []):
            self.third_party.append((p['id'], 'in', payee, purpose, amt, when, None))

        # Purchase bills, front-loaded steel first, paid from KVB.
        material_target = p['contract_basic'] * p['material'] * 1.18
        spent = 0.0
        while spent < material_target:
            progress = min(spent / material_target, 0.99)
            when = p['start'] + timedelta(days=int(span * progress * 0.85) + rng.randint(0, 6))
            if when > self.today:
                break
            vendors = [v for start_at, vs in VENDOR_PHASES if progress >= start_at for v in vs]
            vendor = rng.choice(vendors[-4:])
            size = min(material_target - spent, rng.uniform(40_000, 340_000))
            total = self.purchase_bill(p, vendor, when, max(size, 12_000))
            spent += total

        # Project spend out of Axis, about 7% of the contract over its life.
        spend_target = p['contract_basic'] * (0.07 if p.get('ptype') != 'design' else 0.01)
        spent = 0.0
        while spent < spend_target:
            when = p['start'] + timedelta(days=rng.randint(0, span))
            if when > self.today:
                continue
            cat, payees, remark, (lo, hi) = rng.choices(PROJECT_SPEND, SPEND_WEIGHTS)[0]
            payee = rng.choice(payees)
            amt = round(rng.uniform(lo, hi), -2)
            self.bank_row('axis', self.at(when), self.axis_dr(payee, remark, amt), payee, cat,
                          dr=amt, project=disp)
            spent += amt

    def sales_invoice(self, p, when, items):
        rng = self.rng
        n = len(self.sales) + 1
        inter = p['state'] != '33'
        line_rows, subtotal = [], 0.0
        for sl, it in enumerate(items, 1):
            taxable = round(it['amount'], 2)
            subtotal += taxable
            g9 = round(taxable * 0.09, 2)
            line_rows.append(dict(sl_no=sl, description=it['description'], hsn_sac_code=it['hsn'],
                                  quantity=it['quantity'], uom=it['unit'], rate_per_unit=it['rate'],
                                  taxable_value=taxable,
                                  cgst_rate=0 if inter else 9, cgst_amount=0 if inter else g9,
                                  sgst_rate=0 if inter else 9, sgst_amount=0 if inter else g9,
                                  igst_rate=18 if inter else 0,
                                  igst_amount=round(taxable * 0.18, 2) if inter else 0,
                                  amount=round(taxable * 1.18, 2)))
        subtotal = round(subtotal, 2)
        cgst = 0 if inter else round(sum(l['cgst_amount'] for l in line_rows), 2)
        igst = round(sum(l['igst_amount'] for l in line_rows), 2)
        exact = subtotal + 2 * cgst + igst
        total = round(exact)
        header = dict(filename=f"KSS_INV_{n:03d}.pdf", invoice_number=f"KSS/26-27/{n:03d}",
                      invoice_date=when, irn=self.ref(12) + self.ref(12),
                      ack_number=self.ref(15), vendor_name=COMPANY['name'],
                      vendor_gstin=COMPANY['gstin'], vendor_address=COMPANY['address'],
                      vendor_state=COMPANY['state'], buyer_name=p['client'],
                      buyer_gstin=self.gstin(p['state'], 'AA' + p['client'][:1] + 'C' + p['client'][1:2]),
                      buyer_state=STATE_NAMES[p['state']], subtotal=subtotal, total_cgst=cgst,
                      total_sgst=cgst, total_igst=igst, round_off=round(total - exact, 2),
                      total_amount=total, project=display(p),
                      vehicle_number=f"TN 37 {chr(65 + rng.randint(0, 25))}{chr(65 + rng.randint(0, 25))} {rng.randint(1000, 9999)}"
                      if p.get('ptype') != 'design' else None)
        self.sales.append((header, line_rows, None))
        return when, total

    def purchase_bill(self, p, vendor, when, size, split_with=None):
        rng = self.rng
        state, pan, catalogue = MATERIAL_VENDORS[vendor]
        inter = state != '33'
        items = rng.sample(catalogue, rng.randint(1, min(3, len(catalogue))))
        per_item = size / 1.18 / len(items)
        line_rows, subtotal = [], 0.0
        for sl, (desc, hsn, unit, rate) in enumerate(items, 1):
            qty = max(1, round(per_item / rate, 0 if unit in ('NOS', 'BOX', 'PKT') else 1))
            taxable = round(qty * rate, 2)
            subtotal += taxable
            g9 = round(taxable * 0.09, 2)
            line_rows.append(dict(sl_no=sl, description=desc, hsn_sac_code=hsn, quantity=qty,
                                  uom=unit, rate_per_unit=rate, taxable_value=taxable,
                                  cgst_rate=0 if inter else 9, cgst_amount=0 if inter else g9,
                                  sgst_rate=0 if inter else 9, sgst_amount=0 if inter else g9,
                                  igst_rate=18 if inter else 0,
                                  igst_amount=round(taxable * 0.18, 2) if inter else 0,
                                  amount=round(taxable * 1.18, 2)))
        subtotal = round(subtotal, 2)
        cgst = 0 if inter else round(sum(l['cgst_amount'] for l in line_rows), 2)
        igst = round(sum(l['igst_amount'] for l in line_rows), 2)
        exact = subtotal + 2 * cgst + igst
        total = round(exact)
        n = sum(1 for b in self.bills if b[0]['vendor_name'] == vendor) + 1
        prefix = ''.join(w[0] for w in vendor.split())
        header = dict(filename=f"{prefix}_{n:03d}.pdf", invoice_number=f"{prefix}/{n + 140}/26-27",
                      invoice_date=when, vendor_name=vendor, vendor_gstin=self.gstin(state, pan),
                      vendor_state=STATE_NAMES[state], buyer_name=COMPANY['name'],
                      buyer_gstin=COMPANY['gstin'], buyer_address=COMPANY['address'],
                      buyer_state=COMPANY['state'], subtotal=subtotal, total_cgst=cgst,
                      total_sgst=cgst, total_igst=igst, round_off=round(total - exact, 2),
                      total_amount=total, project=display(p),
                      vehicle_number=f"TN {rng.choice(['37', '38', '66'])} {chr(65 + rng.randint(0, 25))} {rng.randint(1000, 9999)}",
                      transporter_name=rng.choice(['VELU TRANSPORTS', 'Own vehicle', None]))
        allocations = [(display(p), subtotal, cgst, cgst, igst, total)]
        self.bills.append((header, line_rows, allocations))

        # Pay it: most bills in full 7-30 days later, big ones sometimes in two
        # parts, the newest few not yet.
        pay_on = when + timedelta(days=rng.randint(7, 30))
        if pay_on <= self.today and rng.random() < 0.93:
            parts = [total] if total < 250_000 or rng.random() < 0.5 else \
                [round(total * 0.6, -3), total - round(total * 0.6, -3)]
            for i, amt in enumerate(parts):
                d = self.clamp(pay_on + timedelta(days=12 * i))
                if d < self.today or i == 0:
                    self.bank_row('kvb', self.at(d, 10, 17), self.kvb_dr(vendor, amt, 'PURC'),
                                  vendor, 'MATERIAL PURCHASE', dr=amt, project=display(p))
        return total

    def split_one_bill(self):
        """Steel bought for two jobs on one invoice: allocate it 60/40."""
        a, b = (next(p for p in PROJECTS if p['id'] == i) for i in (704, 705))
        for header, lines, allocs in self.bills:
            if (header['project'] == display(a) and header['vendor_name'] == 'ANAND STEEL TRADERS'
                    and header['total_amount'] > 150_000 and len(allocs) == 1):
                _, sub, c, s, i, tot = allocs[0]
                part = lambda v: round(v * 0.6, 2)  # noqa: E731
                allocs[:] = [(display(a), part(sub), part(c), part(s), part(i), part(tot)),
                             (display(b), round(sub - part(sub), 2), round(c - part(c), 2),
                              round(s - part(s), 2), round(i - part(i), 2), round(tot - part(tot), 2))]
                return

    def unbilled_advance(self):
        """A material advance with no bill yet - the reconciler should flag it."""
        p = next(p for p in PROJECTS if p['id'] == 705)
        when = self.clamp(self.today - timedelta(days=9))
        self.bank_row('kvb', self.at(when, 11, 16), self.kvb_dr('ANAND STEEL TRADERS', 300_000, 'ADV'),
                      'ANAND STEEL TRADERS', 'MATERIAL PURCHASE', dr=300_000, project=display(p),
                      source=('manual', None, None))

    def flag_some_bills(self):
        """Freight charged on the bill but not captured as a line: the totals stop
        reconciling, which is exactly what the validator is there to catch. One of
        them has since been checked and approved by a person."""
        candidates = [b for b in self.bills if len(b[1]) >= 2]
        picks = self.rng.sample(candidates, min(4, len(candidates)))
        for i, (header, lines, allocs) in enumerate(picks):
            freight = self.rng.choice([1_180, 1_770, 2_360])
            header['total_amount'] += freight
            header['_approved'] = i == 0
            if allocs:
                last = list(allocs[-1])
                last[5] = round(last[5] + freight, 2)
                allocs[-1] = tuple(last)

    # -- running the business ------------------------------------------------
    def overheads(self):
        rng = self.rng
        d = date(START.year, START.month, 1)
        while d <= self.today:
            month_end = (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
            def on(day):
                return min(d.replace(day=min(day, month_end.day)), self.today)
            for name, pay in STAFF:
                if on(2) <= self.today:
                    self.bank_row('axis', self.at(on(rng.randint(1, 3)), 10, 13),
                                  f"INB/NEFT/AXOIC{self.ref(9)}/{name}/{BANK_NAMES[rng.choice(BANKS)]}/SALARY",
                                  name, 'SALARY AC', dr=pay, source=('manual', None, None))
            self.bank_row('kvb', self.at(on(5)), self.kvb_dr('LAKSHMI PROPERTIES', 38_000, 'RENT'),
                          'LAKSHMI PROPERTIES', 'OFFICE EXPENSES', dr=38_000)
            eb = round(rng.uniform(16_000, 31_000), -1)
            self.bank_row('axis', self.at(on(rng.randint(8, 14))),
                          self.axis_merchant('TN POWER DISTRIBUTION', eb), 'TN POWER DISTRIBUTION',
                          'EB BILL', dr=eb)
            self.bank_row('axis', self.at(on(11)), self.axis_merchant('NETLINK BROADBAND', 1_179),
                          'NETLINK BROADBAND', 'OFFICE EXPENSES', dr=1_179)
            for _ in range(rng.randint(5, 8)):
                cat, payee, remark, lo, hi = rng.choice([
                    ('OFFICE EXPENSES', 'SWIFT STATIONERS', 'office', 300, 4_500),
                    ('OFFICE EXPENSES', 'CITY TEA STALL', 'tea', 400, 2_200),
                    ('OFFICE EXPENSES', 'PROFESSIONAL COURIERS', 'courier', 150, 900),
                    ('FACTORY EXPENSES', 'GANESH WELDING WORKS', 'factory', 2_500, 24_000),
                    ('FACTORY EXPENSES', 'BALU ENGINEERING', 'machine repair', 3_000, 36_000),
                    ('FACTORY EXPENSES', 'ARUN M', 'factory', 1_500, 9_000),
                    ('TRAVELLING EXPENSES', 'SRI RAM FUELS', 'fuel', 1_500, 6_000),
                ])
                amt = round(rng.uniform(lo, hi), -1)
                day = on(rng.randint(1, 28))
                desc = (self.axis_merchant(payee, amt) if payee in ('SRI RAM FUELS', 'CITY TEA STALL')
                        else self.axis_dr(payee, remark, amt))
                self.bank_row('axis', self.at(day), desc, payee, cat, dr=amt)
            for day in (rng.randint(3, 9), rng.randint(16, 24)):  # petty cash for the site box
                amt = rng.choice([10_000, 15_000, 20_000])
                when = on(day)
                self.bank_row('axis', self.at(when), f"ATM-CASH/AXIS/{self.ref(6)}/COIMBATORE",
                              'CASH WITHDRAWAL', 'PETTY CASH', dr=amt, source=('manual', None, None))
                self.petty_cash(when, amt)
            for bank in ('axis', 'kvb'):
                chg = rng.choice([118, 177, 236, 354, 590])
                desc = ('Consolidated Charges for A/c' if bank == 'axis'
                        else f"CHGS-NEFT/RTGS CHARGES {d.strftime('%b%y').upper()}")
                self.bank_row(bank, self.at(month_end if month_end <= self.today else self.today, 18, 20),
                              desc, 'BANK', 'BANK CHARGES', dr=chg, source=('keyword', None, None))
            d = month_end + timedelta(days=1)

    def petty_cash(self, when, amount):
        """The site box spends what was drawn, a few hundred at a time."""
        rng = self.rng
        self.personal.append((when, 'Axis ATM', 'Cash drawn for site box', 'General', amount,
                              'income', 'axis'))
        left = amount
        live = [p for p in PROJECTS if p['start'] <= when <= (p['end'] or self.today)
                and p.get('ptype') != 'design']
        while left > 300:
            vendor, desc, lo, hi = rng.choice([
                ('Tea shop', 'Tea & snacks for site crew', 150, 900),
                ('Auto stand', 'Auto fare - material pickup', 120, 600),
                ('Petrol bunk', 'Diesel for site generator', 800, 3_000),
                ('Hardware shop', 'Cutting wheels, gloves, rope', 300, 2_400),
                ('Labour bata', 'Food allowance - night shift', 500, 2_000),
                ('Xerox shop', 'Drawing prints', 80, 450),
            ])
            amt = min(left, round(rng.uniform(lo, hi), -1))
            proj = display(rng.choice(live)) if live and rng.random() < 0.75 else 'General'
            self.personal.append((self.clamp(when + timedelta(days=rng.randint(0, 10))), vendor,
                                  desc, proj, amt, 'expense', 'axis'))
            left -= amt

    def gst_payments(self):
        """GSTR-3B on the 20th: last month's output GST less input GST."""
        d = date(START.year, START.month, 1)
        while True:
            nxt = (d.replace(day=28) + timedelta(days=4)).replace(day=1)
            due = nxt.replace(day=20)
            if due > self.today:
                break
            def gst(rows):
                return sum(h['total_cgst'] + h['total_sgst'] + h['total_igst'] for h, _, _ in rows
                           if d <= h['invoice_date'] < nxt)
            payable = round(gst(self.sales) - gst(self.bills))
            if payable > 0:
                self.bank_row('kvb', self.at(due, 11, 15),
                              f"GST-CPIN 2633{self.ref(10)} {d.strftime('%b%y').upper()}",
                              'GST PAYMENT', 'DUTIES & TAX', dr=payable, source=('manual', None, None))
            d = nxt

    def keep_balances_positive(self):
        """Promoter capital opens KVB; Axis is topped up from KVB when it runs low."""
        rng = self.rng
        self.bank_row('kvb', self.at(START, 10, 11), self.kvb_cr('R VENKATESH', 1_500_000),
                      'R VENKATESH', 'CAPITAL AC', cr=1_500_000, source=('manual', None, None))

        def transfer(when, amt):
            ref = self.ref()
            self.bank_row('kvb', when, f"IMPS-{ref}-KAVERISTEELSTR-UTIB-xxxxxxxxxxx4417-TRF",
                          COMPANY['name'], 'AMOUNT TRANSFER', dr=amt, source=('manual', None, None))
            self.bank_row('axis', when + timedelta(minutes=1),
                          f"IMPS/P2A/{ref}/KAVERI STEEL STRUCT/KVB/Trf", COMPANY['name'],
                          'AMOUNT TRANSFER', cr=amt, source=('manual', None, None))

        transfer(self.at(START, 11, 12), 300_000)
        self.axis.sort(key=lambda r: r[0])
        bal, i = 0.0, 0
        while i < len(self.axis):
            r = self.axis[i]
            if bal + r[9] - r[8] < 60_000:
                amt = rng.choice([200_000, 300_000, 400_000, 500_000])
                transfer(r[0] - timedelta(hours=2), amt)
                self.axis.sort(key=lambda r: r[0])
                bal, i = 0.0, 0
                continue
            bal += r[9] - r[8]
            i += 1

        self.kvb.sort(key=lambda r: r[0])
        bal = 0.0
        for r in list(self.kvb):
            if bal + r[9] - r[8] < 100_000:
                amt = 1_000_000
                self.bank_row('kvb', r[0] - timedelta(hours=3), self.kvb_cr('R VENKATESH', amt),
                              'R VENKATESH', 'CAPITAL AC', cr=amt, source=('manual', None, None))
                bal += amt
            bal += r[9] - r[8]
        self.kvb.sort(key=lambda r: r[0])

    def build(self):
        self.build_projects()
        self.split_one_bill()
        self.unbilled_advance()
        self.flag_some_bills()
        self.overheads()
        self.gst_payments()
        self.keep_balances_positive()
        self.mark_needs_review()
        return self

    def mark_needs_review(self):
        """The newest upload's unsure rows: the category memory saw this payee go
        both ways and left the call to a person."""
        rng = self.rng
        cutoff = datetime.combine(self.today - timedelta(days=24), time())
        contested = {'SITE EXPENSES': 'FACTORY EXPENSES', 'FACTORY EXPENSES': 'SITE EXPENSES',
                     'TRANSPORT EXPENSES': 'CRANE RENT', 'CRANE RENT': 'TRANSPORT EXPENSES',
                     'LABOUR PAYMENT': 'SITE EXPENSES'}
        pool = [r for r in self.axis if r[0] >= cutoff and r[3] in contested]
        for r in rng.sample(pool, min(14, len(pool))):
            share = rng.randint(55, 72)
            r[7] = (f"{r[2]}: {share}% of ~{rng.randint(9, 30)} past payments were {r[3]}, "
                    f"the rest {contested[r[3]]} — depends which job, so left for you to assign")
            r[3], r[4], r[5], r[10] = 'UNCATEGORIZED', 'UC', 'suggested', None
            r[6] = round(rng.uniform(0.58, 0.74), 3)


# ---------------------------------------------------------------------------
# Writing it out
# ---------------------------------------------------------------------------

TXN_COLS = ("transaction_date, transaction_description, client_vendor, category, code, "
            "category_source, category_confidence, category_note, dr_amount, cr_amount, project")
INVOICE_COLS = ['filename', 'invoice_number', 'invoice_date', 'irn', 'ack_number', 'vendor_name',
                'vendor_gstin', 'vendor_address', 'vendor_state', 'buyer_name', 'buyer_gstin',
                'buyer_address', 'buyer_state', 'subtotal', 'total_cgst', 'total_sgst', 'total_igst',
                'round_off', 'total_amount', 'vehicle_number', 'transporter_name', 'project',
                'validation_status', 'validation_diff', 'validation_notes', 'validation_reviewed_note']
LINE_COLS = ['sl_no', 'description', 'hsn_sac_code', 'quantity', 'uom', 'rate_per_unit',
             'taxable_value', 'cgst_rate', 'cgst_amount', 'sgst_rate', 'sgst_amount',
             'igst_rate', 'igst_amount', 'amount']


def _insert_invoices(cur, table, items_table, rows):
    for header, lines, allocs in rows:
        result = validate_db_row(header, lines)
        header['validation_status'] = result['status']
        header['validation_diff'] = result['diff']
        header['validation_notes'] = notes_from_result(result) or None
        if header.pop('_approved', False) and result['status'] != 'ok':
            header['validation_status'] = 'approved'
            header['validation_reviewed_note'] = ('Freight charged separately on the bill - '
                                                  'checked against the original copy.')
        cur.execute(f"INSERT INTO {table} ({', '.join(INVOICE_COLS)}) VALUES "
                    f"({', '.join(['%s'] * len(INVOICE_COLS))})",
                    [header.get(c) for c in INVOICE_COLS])
        inv_id = cur.lastrowid
        cur.executemany(f"INSERT INTO {items_table} (invoice_id, {', '.join(LINE_COLS)}) VALUES "
                        f"({inv_id}, {', '.join(['%s'] * len(LINE_COLS))})",
                        [[l[c] for c in LINE_COLS] for l in lines])
        for seq, alloc in enumerate(allocs or [], 1):
            cur.execute("INSERT INTO bill_project_allocations (invoice_id, seq, project, alloc_taxable, "
                        "alloc_cgst, alloc_sgst, alloc_igst, alloc_total) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (inv_id, seq) + tuple(alloc))


def seed(conn, today=None):
    g = Gen(today or date.today()).build()
    cur = conn.cursor()

    cur.executemany("INSERT INTO categories (category_name, category_code) VALUES (%s, %s)",
                    CATEGORIES)

    for p in PROJECTS:
        cur.execute("INSERT INTO projects (id, stem_name, description, is_project, project_type, "
                    "is_inactive, overhead) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (p['id'], p['stem'], f"{p['client'].title()} - {STATE_NAMES[p['state']]}",
                     1, p.get('ptype', 'project'), int(p.get('inactive', False)), p['overhead']))
    for po in g.po:
        cur.execute("INSERT INTO project_pos (project_id, po_number, po_date, client_name, currency, "
                    "taxable_value, total_tax, total_value, line_item_count, line_items, payment_terms, "
                    "source_filename, extraction_status) "
                    "VALUES (%s, %s, %s, %s, 'INR', %s, %s, %s, %s, %s, %s, %s, 'manual')",
                    (po['project_id'], po['po_number'], po['po_date'], po['client_name'],
                     po['taxable_value'], po['total_tax'], po['total_value'], len(po['line_items']),
                     json.dumps(po['line_items']), PAYMENT_TERMS, f"PO_{po['project_id']}.pdf"))
    for kind, pid, desc, qty, unit, rate, basic, when in g.ledgers:
        table, date_col = (('project_po_variations', 'variation_date') if kind == 'variation'
                           else ('project_po_actuals', 'actual_date'))
        tax = round(basic * 0.18, 2)
        cur.execute(f"INSERT INTO {table} (project_id, description, quantity, unit, rate, gst_rate, "
                    f"basic_amount, tax_amount, total_amount, {date_col}) "
                    "VALUES (%s, %s, %s, %s, %s, 18, %s, %s, %s, %s)",
                    (pid, desc, qty, unit, rate, basic, tax, basic + tax, when))
    cur.executemany("INSERT INTO project_cash_payments (project_id, amount, payment_date, note) "
                    "VALUES (%s, %s, %s, %s)", g.cash)
    cur.executemany("INSERT INTO project_third_party_payments (project_id, direction, payee, purpose, "
                    "amount, payment_date, note) VALUES (%s, %s, %s, %s, %s, %s, %s)", g.third_party)

    counts = {}
    for bank, table, rows in (('axis', 'axis_transactions', g.axis), ('kvb', 'kvb_transactions', g.kvb)):
        cur.executemany(f"INSERT INTO {table} ({TXN_COLS}) VALUES ({', '.join(['%s'] * 11)})",
                        [tuple(r) for r in rows])
        counts[bank] = len(rows)
        months = sorted({r[0].strftime('%Y-%m') for r in rows})
        for m in months:
            n = sum(1 for r in rows if r[0].strftime('%Y-%m') == m)
            cur.execute("INSERT INTO bank_upload_history (bank_code, filename, upload_date, "
                        "records_processed, records_inserted, status) "
                        "VALUES (%s, %s, %s, %s, %s, 'success')",
                        (bank, f"{bank.upper()}_statement_{m}.xlsx",
                         datetime.strptime(m + '-01', '%Y-%m-%d') + timedelta(days=33), n, n))
    # The legacy table mirrors Axis.
    cur.executemany("INSERT INTO transactions (transaction_date, transaction_description, client_vendor, "
                    "category, code, dr_amount, cr_amount, project) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    [tuple(r[:5] + r[8:]) for r in g.axis])

    _insert_invoices(cur, 'bill_invoices', 'bill_line_items', g.bills)
    _insert_invoices(cur, 'sales_invoices', 'sales_line_items', g.sales)

    cur.executemany("INSERT INTO personal_transactions (transaction_date, vendor, description, project, "
                    "amount, transaction_type, bank) VALUES (%s, %s, %s, %s, %s, %s, %s)", g.personal)
    conn.commit()

    review = sum(1 for r in g.axis + g.kvb if r[5] == 'suggested')
    return {'projects': len(PROJECTS), 'axis': counts['axis'], 'kvb': counts['kvb'],
            'purchase_bills': len(g.bills), 'sales_invoices': len(g.sales),
            'personal': len(g.personal), 'needs_review': review,
            'bills_flagged': sum(1 for h, _, _ in g.bills if h['validation_status'] != 'ok')}
