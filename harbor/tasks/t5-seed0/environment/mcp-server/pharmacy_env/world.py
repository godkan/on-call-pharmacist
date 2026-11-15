"""Static hospital data. All names of the hospital, staff, patients and lots are fictional;
drug names follow common generic names and pack presentations. Usage rates, prices and the
cold-chain guidance table are invented for this environment."""

HOSPITAL = "Kymijoki Regional Hospital"

CENTRAL = "CENTRAL"
# Clinical areas with an automated cabinet, plus the out-of-hours cupboard (night shifts only).
WARDS = ["ICU", "ED", "SURG", "PED", "MED", "THEATRE", "MAT", "NIGHT"]
PATIENT_WARDS = ["ICU", "ED", "SURG", "PED", "MED", "MAT"]       # wards with inpatients
NIGHT_ONLY = ["NIGHT"]
LOCATIONS = [CENTRAL] + WARDS
LOCATION_NAMES = {
    "CENTRAL": "Central Pharmacy store",
    "ICU": "Intensive Care Unit cabinet",
    "ED": "Emergency Department cabinet",
    "SURG": "Surgical Wards cabinet",
    "PED": "Paediatrics cabinet",
    "MED": "Medical Wards cabinet",
    "THEATRE": "Operating Theatres cabinet",
    "MAT": "Maternity Unit cabinet",
    "NIGHT": "Out-of-hours emergency cupboard (used when the pharmacy is closed)",
}
# Weight of a missed dose by area (shortage allocation policy P-12).
WARD_WEIGHT = {"ICU": 1.5, "ED": 1.5, "THEATRE": 1.5, "MAT": 1.5, "SURG": 1.0, "PED": 1.0, "MED": 1.0,
               "NIGHT": 1.0}

CATEGORIES = {
    "resus": "Resuscitation and vasoactive",
    "anticoag": "Anticoagulation and reversal",
    "antiinfective": "Anti-infectives",
    "analgesia": "Analgesia, sedation and anaesthesia",
    "nmb": "Neuromuscular blockade and reversal",
    "endocrine": "Insulin and glucose",
    "gi": "Gastrointestinal and antiemetic",
    "fluids": "Fluids and electrolytes",
    "womens_child": "Obstetrics and paediatrics",
}

# id: name, unit price (EUR), critical, mean units used per 12 h shift by area
# (ICU, ED, SURG, PED, MED, THEATRE, MAT, NIGHT), lot prefix, category
DRUGS = {
    # resuscitation and vasoactive
    "EPI-1MG": ("Epinephrine 1 mg/mL injection, 1 mL ampoule", 4.20, True, (3, 4, 1, 1, 1, 1, 1, 1), "EP", "resus"),
    "NOR-4MG": ("Norepinephrine 4 mg/4 mL concentrate for infusion, ampoule", 6.80, True, (7, 2, 1, 0, 0, 1, 0, 0), "NA", "resus"),
    "AMIO-150": ("Amiodarone 50 mg/mL injection, 3 mL ampoule", 3.80, True, (2, 2, 0, 0, 1, 0, 0, 1), "AM", "resus"),
    "ATR-600": ("Atropine sulfate 600 micrograms/mL injection, 1 mL ampoule", 2.20, True, (1, 2, 1, 0, 0, 3, 0, 1), "AT", "resus"),
    # anticoagulation and reversal
    "HEP-5K": ("Heparin sodium 5,000 IU/mL injection, 5 mL vial", 5.90, True, (5, 1, 3, 0, 2, 1, 0, 1), "HP", "anticoag"),
    "ENOX-40": ("Enoxaparin 40 mg/0.4 mL prefilled syringe", 3.30, False, (2, 1, 6, 0, 8, 0, 3, 0), "EX", "anticoag"),
    "PROT-50": ("Protamine sulfate 10 mg/mL injection, 5 mL ampoule", 9.50, True, (0.5, 0, 0, 0, 0, 1, 0, 0), "PR", "anticoag"),
    # anti-infectives
    "CTX-1G": ("Ceftriaxone 1 g powder for solution for injection, vial", 2.90, True, (3, 4, 2, 3, 5, 0, 1, 0), "CT", "antiinfective"),
    "CTAX-1G": ("Cefotaxime 1 g powder for solution for injection, vial", 3.40, False, (1, 1, 0, 1, 1, 0, 0, 0), "CX", "antiinfective"),
    "PIP-45": ("Piperacillin/tazobactam 4 g/0.5 g powder for infusion, vial", 7.60, True, (6, 2, 3, 1, 3, 0, 0, 1), "PT", "antiinfective"),
    "MEM-1G": ("Meropenem 1 g powder for solution for injection, vial", 11.40, True, (3, 0, 1, 0, 1, 0, 0, 0), "ME", "antiinfective"),
    "VAN-1G": ("Vancomycin 1 g powder for infusion, vial", 8.90, True, (3, 1, 1, 1, 2, 0, 0, 0), "VA", "antiinfective"),
    "OSE-75": ("Oseltamivir 75 mg capsules, pack of 10", 14.00, False, (1, 1, 0, 1, 2, 0, 0, 0), "OS", "antiinfective"),
    # analgesia, sedation and anaesthesia
    "MOR-10": ("Morphine sulfate 10 mg/mL injection, 1 mL ampoule", 1.70, True, (3, 3, 4, 0, 2, 1, 1, 1), "MS", "analgesia"),
    "FEN-100": ("Fentanyl 50 micrograms/mL injection, 2 mL ampoule", 1.40, True, (4, 1, 0, 0, 0, 8, 1, 0), "FE", "analgesia"),
    "MID-5": ("Midazolam 1 mg/mL injection, 5 mL ampoule", 1.10, True, (3, 1, 0, 1, 0, 3, 0, 0), "MZ", "analgesia"),
    "PROP-200": ("Propofol 10 mg/mL emulsion for injection, 20 mL ampoule", 2.60, True, (3, 0, 0, 0, 0, 8, 0, 0), "PF", "analgesia"),
    # neuromuscular blockade and reversal
    "SUX-100": ("Suxamethonium chloride 50 mg/mL injection, 2 mL ampoule", 3.10, True, (1, 2, 2, 0, 0, 3, 1, 0), "SX", "nmb"),
    "ROC-50": ("Rocuronium bromide 10 mg/mL injection, 5 mL vial", 4.60, True, (3, 1, 3, 0, 0, 6, 0, 0), "RC", "nmb"),
    "SUG-200": ("Sugammadex 100 mg/mL injection, 2 mL vial", 88.00, False, (0, 0, 0, 0, 0, 1, 0, 0), "SG", "nmb"),
    # insulin and glucose
    "INS-REG": ("Insulin human (regular) 100 IU/mL, 10 mL vial", 18.50, True, (2, 1, 1, 1, 2, 0, 1, 1), "IR", "endocrine"),
    "INS-GLA": ("Insulin glargine 100 IU/mL, 3 mL prefilled pen", 9.80, False, (0, 0, 1, 1, 3, 0, 0, 0), "IG", "endocrine"),
    "GLU-50": ("Glucose 50% solution for injection, 50 mL vial", 3.20, True, (1, 2, 0, 0, 1, 0, 0, 1), "GL", "endocrine"),
    # gastrointestinal and antiemetic
    "OND-4": ("Ondansetron 4 mg/2 mL injection, ampoule", 1.20, False, (1, 3, 5, 1, 2, 4, 2, 0), "ON", "gi"),
    "PAN-40": ("Pantoprazole 40 mg powder for solution for injection, vial", 2.80, False, (2, 1, 2, 0, 3, 0, 0, 0), "PZ", "gi"),
    # fluids and electrolytes
    "NS-1000": ("Sodium chloride 0.9% solution for infusion, 1000 mL bag", 1.60, False, (20, 30, 25, 6, 22, 15, 8, 2), "NS", "fluids"),
    "KCL-20": ("Potassium chloride 2 mmol/mL concentrate for infusion, 10 mL ampoule", 1.30, True, (2, 0, 0, 0, 0, 1, 0, 0), "KC", "fluids"),
    "PCM-IV": ("Paracetamol 10 mg/mL solution for infusion, 100 mL vial", 1.90, False, (4, 5, 9, 2, 3, 3, 2, 1), "PC", "fluids"),
    # obstetrics and paediatrics
    "OXY-10": ("Oxytocin 10 IU/mL injection, 1 mL ampoule", 1.90, True, (0, 0, 0, 0, 0, 0, 6, 0), "OX", "womens_child"),
    "PCM-SUS": ("Paracetamol 120 mg/5 mL oral suspension, 100 mL bottle", 2.10, False, (0, 0, 0, 2, 0, 0, 0, 0), "PS", "womens_child"),
}
PRODUCTS = list(DRUGS)

# The ten products of the first versions of this environment.
BASE_PRODUCTS = ["EPI-1MG", "NOR-4MG", "HEP-5K", "INS-REG", "CTX-1G", "CTAX-1G", "PIP-45", "MOR-10",
                 "OND-4", "PCM-IV"]

# Hospital cold-chain guidance table (synthetic, for this environment): storage 2-8 C.
# max_c: highest temperature allowed during an excursion; max_hours: cumulative hours allowed
# outside 2-8 C over the life of the batch; freeze: True if any reading below 0 C means discard.
COLD_RULES = {
    "INS-REG": {"max_c": 25, "max_hours": 672, "freeze": True},
    "INS-GLA": {"max_c": 30, "max_hours": 672, "freeze": True},
    "SUX-100": {"max_c": 25, "max_hours": 336, "freeze": True},
    "ROC-50": {"max_c": 30, "max_hours": 1440, "freeze": False},
    "OXY-10": {"max_c": 30, "max_hours": 2160, "freeze": True},
}
COLD_PRODUCTS = list(COLD_RULES)

CONTROLLED = {"MOR-10", "FEN-100", "MID-5"}             # register entries and counts required
HIGH_ALERT = {"KCL-20", "INS-REG", "HEP-5K"}            # high-alert medicines (ISMP-style list)
# Concentrated potassium may only be stocked in these areas (hospital policy).
RESTRICTED_STORAGE = {"KCL-20": ["CENTRAL", "ICU", "THEATRE"]}
LOOK_ALIKE = {"INS-REG": "INS-GLA", "INS-GLA": "INS-REG", "PCM-IV": "PCM-SUS", "PCM-SUS": "PCM-IV"}
RESTRICTED_ANTIMICROBIALS = {"MEM-1G", "VAN-1G"}         # infectious diseases approval for new starts
VOLUME = {"NS-1000": 4, "PCM-IV": 2, "PROP-200": 2}      # storage units per pack (default 1)

# Formulary-approved therapeutic alternatives (Pharmacy & Therapeutics Committee list F-3).
ALTERNATIVES = {"CTX-1G": ["CTAX-1G", "PIP-45"], "CTAX-1G": ["CTX-1G"], "SUX-100": ["ROC-50"]}
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


def prefix(d):
    return DRUGS[d][4]


def category(d):
    return DRUGS[d][5]


def usage(d, ward):
    return DRUGS[d][3][WARDS.index(ward)]


def total_usage(d):
    """Mean use per shift over the whole hospital (the out-of-hours cupboard is open every other shift)."""
    return sum(u * (0.5 if w in NIGHT_ONLY else 1.0) for w, u in zip(WARDS, DRUGS[d][3]))


def cabinet_par(d, ward):
    return usage(d, ward) * CABINET_PAR_SHIFTS


def central_par(d):
    return total_usage(d) * CENTRAL_PAR_SHIFTS


def attributes(d):
    """Formulary attributes shown to the pharmacist."""
    out = {"category": CATEGORIES[category(d)]}
    if d in CONTROLLED:
        out["controlled_drug"] = "Schedule 2: register entry for every movement; counted daily"
    if d in HIGH_ALERT:
        out["high_alert"] = True
    if d in RESTRICTED_STORAGE:
        out["stock_only_in"] = RESTRICTED_STORAGE[d]
    if d in LOOK_ALIKE:
        out["look_alike_sound_alike_with"] = LOOK_ALIKE[d]
    if d in RESTRICTED_ANTIMICROBIALS:
        out["restricted_antimicrobial"] = "New courses need infectious diseases approval"
    if VOLUME.get(d, 1) > 1:
        out["storage_units_per_pack"] = VOLUME[d]
    return out
