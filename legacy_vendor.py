"""
Frozen copy of the pre-rewrite vendor extractor.

Kept for exactly one purpose: deciding whether a stored client_vendor value was
written by the old parser or edited by a human. If a row still matches what this
function would have produced, no one has touched it and it is safe to correct.
Anything that differs carries human knowledge and must be left alone.

Do not use this for extraction - vendor_extractor.py is the live implementation.
"""

import re
from typing import Optional


def legacy_extract_vendor(particulars: str, bank_code: str = 'axis') -> Optional[str]:
    """
    Extract vendor/client name from transaction particulars
    Handles UPI, IMPS, NEFT patterns common in bank statements

    Args:
        particulars: Transaction description
        bank_code: Bank code ('axis' or 'kvb') for bank-specific patterns

    Returns:
        Vendor name or None
    """
    if not particulars or not isinstance(particulars, str):
        return None

    particulars = particulars.strip()

    # KVB-specific patterns (different format from Axis)
    if bank_code == 'kvb':
        # KVB IMPS: IMPS-509113479708-VISMAASSOCIATES-UTIB-xxxxxxxxxxx
        kvb_imps = re.search(r'IMPS-\d+-([A-Za-z\s]+)-[A-Z]{4}-', particulars)
        if kvb_imps:
            return kvb_imps.group(1).strip()

        # KVB NEFT CR: NEFT CR-CNRB0000967-SV CONSTRUCTIONS-VISMA ASSOCIA
        kvb_neft_cr = re.search(r'NEFT CR-[A-Z0-9]+-([^-]+)-', particulars)
        if kvb_neft_cr:
            return kvb_neft_cr.group(1).strip()

        # KVB NEFT DR: NEFT DR-KVBLH00232446439-VISMAASSOCIATES-UTIB00004
        kvb_neft_dr = re.search(r'NEFT DR-[A-Z0-9]+-([^-]+)-', particulars)
        if kvb_neft_dr:
            return kvb_neft_dr.group(1).strip()

        # KVB UPI-CR: UPI-CR-102477049440-SRIRAM R-HDFC-50100004440849-U
        kvb_upi = re.search(r'UPI-(?:CR|DR)-\d+-([^-]+)-[A-Z]{4}-', particulars)
        if kvb_upi:
            return kvb_upi.group(1).strip()

        # CASH DEP: CASH DEP-SELF-SEETHALAKSHMI-CBE-RAMANATH
        cash_dep = re.search(r'CASH DEP-[^-]+-([^-]+)-', particulars)
        if cash_dep:
            return cash_dep.group(1).strip()

        # ECS/NACH: To Clg:ECS BD-TATA MF - NACH
        ecs_match = re.search(r'ECS (?:BD|TP ACH)\s*-?\s*([^-]+)\s*-?\s*NACH', particulars, re.IGNORECASE)
        if ecs_match:
            return ecs_match.group(1).strip()

        # MB-WITHIN (internal transfers): MB-WITHIN-DR:XXXX4008-CR:XXXX0334-...
        if 'MB-WITHIN' in particulars:
            return 'Internal Transfer'

        # Fallback: Extract name from hyphen-separated parts
        parts = [p.strip() for p in particulars.split('-') if p.strip()]
        if len(parts) >= 3:
            # Skip transaction type and ID, look for name
            for part in parts[2:]:
                # Skip account numbers, codes, and numeric parts
                if part and not part.isdigit() and len(part) > 2:
                    if not re.match(r'^[A-Z]{4}\d*$', part) and not re.match(r'^x+\d*$', part, re.IGNORECASE):
                        return part
        return None

    # Axis Bank patterns (original logic)
    # UPI patterns: UPI/P2M/xxx/VENDOR NAME/...
    upi_match = re.search(r'UPI/P2[AM]/\d+/([^/]+)', particulars)
    if upi_match:
        vendor = upi_match.group(1).strip()
        # Clean up common suffixes
        vendor = re.sub(r'\s+(UPI|MERCHANT|PAY TO|PAYMENT).*$', '', vendor, flags=re.IGNORECASE)
        return vendor

    # IMPS patterns: IMPS/P2A/xxx/VENDOR/...
    imps_match = re.search(r'IMPS/P2A/\d+/([^/]+)', particulars)
    if imps_match:
        vendor = imps_match.group(1).strip()
        return vendor

    # NEFT/RTGS patterns
    neft_match = re.search(r'(?:NEFT|RTGS)[^/]*/([^/]+)', particulars)
    if neft_match:
        vendor = neft_match.group(1).strip()
        return vendor

    # Fallback: Take first meaningful part before /
    parts = [p.strip() for p in particulars.split('/') if p.strip()]
    if len(parts) >= 2:
        # Skip transaction type (UPI, IMPS, etc) and ID, get the vendor
        for part in parts[2:]:
            if part and not part.isdigit() and len(part) > 3:
                return part

    return None
