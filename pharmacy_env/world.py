"""Static hospital data. All names of the hospital, staff and lots are fictional;
drug names follow common generic names and pack presentations."""

HOSPITAL = "Kymijoki Regional Hospital"

CENTRAL = "CENTRAL"
WARDS = ["ICU", "ED", "SURG", "PED", "MED"]
LOCATIONS = [CENTRAL] + WARDS
LOCATION_NAMES = {
    "CENTRAL": "Central Pharmacy store",
    "ICU": "Intensive Care Unit cabinet",
    "ED": "Emergency Department cabinet",
    "SURG": "Surgical Wards cabinet",
    "PED": "Paediatrics cabinet",
    "MED": "Medical Wards cabinet",
}
# Weight of a missed dose by ward (shortage allocation policy P-12).
WARD_WEIGHT = {"ICU": 1.5, "ED": 1.5, "SURG": 1.0, "PED": 1.0, "MED": 1.0}

# id: name, unit price (EUR), critical, mean units used per 12 h shift by ward
# (ICU, ED, SURG, PED, MED), lot prefix
DRUGS = {
    "EPI-1MG": ("Epinephrine 1 mg/mL injection, 1 mL ampoule", 4.20, True, (3, 4, 1, 1, 1), "EP"),
    "NOR-4MG": ("Norepinephrine 4 mg/4 mL concentrate for infusion, ampoule", 6.80, True, (7, 2, 1, 0, 0), "NA"),
    "HEP-5K": ("Heparin sodium 5,000 IU/mL injection, 5 mL vial", 5.90, True, (5, 1, 3, 0, 2), "HP"),
    "INS-REG": ("Insulin human (regular) 100 IU/mL, 10 mL vial", 18.50, True, (2, 1, 1, 1, 2), "IR"),
    "CTX-1G": ("Ceftriaxone 1 g powder for solution for injection, vial", 2.90, True, (3, 4, 2, 3, 5), "CT"),
    "CTAX-1G": ("Cefotaxime 1 g powder for solution for injection, vial", 3.40, False, (1, 1, 0, 1, 1), "CX"),
    "PIP-45": ("Piperacillin/tazobactam 4 g/0.5 g powder for infusion, vial", 7.60, True, (6, 2, 3, 1, 3), "PT"),
    "MOR-10": ("Morphine sulfate 10 mg/mL injection, 1 mL ampoule", 1.70, True, (3, 3, 4, 0, 2), "MS"),
    "OND-4": ("Ondansetron 4 mg/2 mL injection, ampoule", 1.20, False, (1, 3, 5, 1, 2), "ON"),
    "PCM-IV": ("Paracetamol 10 mg/mL solution for infusion, 100 mL vial", 1.90, False, (4, 5, 9, 2, 3), "PC"),
    # Refrigerated products used only in tasks that model the cold chain.
    "SUX-100": ("Suxamethonium chloride 50 mg/mL injection, 2 mL ampoule", 3.10, True, (1, 2, 2, 0, 0), "SX"),
    "ROC-50": ("Rocuronium bromide 10 mg/mL injection, 5 mL vial", 4.60, True, (3, 1, 3, 0, 0), "RC"),
}
BASE_PRODUCTS = ["EPI-1MG", "NOR-4MG", "HEP-5K", "INS-REG", "CTX-1G", "CTAX-1G", "PIP-45", "MOR-10",
                 "OND-4", "PCM-IV"]
COLD_PRODUCTS = ["INS-REG", "SUX-100", "ROC-50"]

# Hospital cold-chain guidance table (synthetic, for this environment): storage 2-8 C.
# max_c: highest temperature allowed during an excursion; max_hours: cumulative hours allowed
# outside 2-8 C over the life of the batch; freeze: True if any reading below 0 C means discard.
COLD_RULES = {
    "INS-REG": {"max_c": 25, "max_hours": 672, "freeze": True},
    "SUX-100": {"max_c": 25, "max_hours": 336, "freeze": True},
    "ROC-50": {"max_c": 30, "max_hours": 1440, "freeze": False},
}

# Formulary-approved therapeutic alternatives (Pharmacy & Therapeutics Committee list F-3).
ALTERNATIVES = {"CTX-1G": ["CTAX-1G", "PIP-45"], "CTAX-1G": ["CTX-1G"]}
# Alternatives that must not be given to patients with this allergy.
RESTRICTIONS = {"PIP-45": "penicillin"}

CABINET_PAR_SHIFTS = 4      # ward cabinet par level = 4 shifts of mean use
CENTRAL_PAR_SHIFTS = 12     # central store par level
DELIVERY_EVERY_SHIFTS = 4   # routine wholesaler delivery every 2 days (day shift)
EMERGENCY_MARKUP = 0.40     # RapidRx urgent order surcharge


def drug_name(d):
    return DRUGS[d][0]


def price(d):
    return DRUGS[d][1]


def critical(d):
    return DRUGS[d][2]


def usage(d, ward):
    return DRUGS[d][3][WARDS.index(ward)]


def total_usage(d):
    return sum(DRUGS[d][3])


def cabinet_par(d, ward):
    return usage(d, ward) * CABINET_PAR_SHIFTS


def central_par(d):
    return total_usage(d) * CENTRAL_PAR_SHIFTS
