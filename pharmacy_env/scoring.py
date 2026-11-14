"""Penalty and normalised score. Lower penalty is better.

score = (P_do_nothing - P) / (P_do_nothing - P_reference)
so the do-nothing anchor scores 0 and the reference pharmacist scores 1 on
every seed.
"""
from . import world as W

WEIGHTS = {
    "recalled_given": 10.0,      # per recalled unit given to a patient after the notice
    "shortfall_critical": 2.0,   # per critical unit a ward could not issue (x ward weight)
    "shortfall_other": 0.5,
    "wrong_quarantine": 0.5,     # per good unit withdrawn
    "urgent_premium": 1 / 25.0,  # per EUR of urgent-order surcharge
    "missed_shift": 5.0,
    "contraindicated": 15.0,     # per dose of an alternative given to a patient allergic to it
}


def penalty(m):
    short = 0.0
    for (ward, drug), units in m["shortfall"].items():
        w = WEIGHTS["shortfall_critical"] if W.critical(drug) else WEIGHTS["shortfall_other"]
        short += units * w * W.WARD_WEIGHT[ward]
    parts = {
        "recalled_given": m["recalled_given"] * WEIGHTS["recalled_given"],
        "shortfall": short,
        "wrong_quarantine": m["wrong_quarantine_units"] * WEIGHTS["wrong_quarantine"],
        "urgent_premium": m["urgent_premium"] * WEIGHTS["urgent_premium"],
        "missed_shifts": m["missed_shifts"] * WEIGHTS["missed_shift"],
        "contraindicated": m.get("contraindicated_given", 0) * WEIGHTS["contraindicated"],
    }
    parts["total"] = sum(parts.values())
    return parts


def normalised(p, p_nothing, p_ref):
    if p_nothing - p_ref <= 1e-9:
        return float("nan")
    return (p_nothing - p) / (p_nothing - p_ref)
