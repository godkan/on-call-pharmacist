"""Task generators. Each returns a task dict for engine.Env."""
import random

from . import world as W

TAG = "26K"   # lot tag of routine wholesaler deliveries during the rota


def _lot_code(rng, prefix):
    return "%s%d%s%03d" % (prefix, rng.choice([24, 25]), rng.choice("ABCDEFGH"), rng.randint(100, 999))


def _initial_stock(rng, products=None):
    """Two lots per product: an older one (A) and a newer one (B). Cabinets mostly
    hold the older lot because they were filled from central earlier."""
    stock, lots = [], {}
    for d in (products or W.PRODUCTS):
        pre = W.prefix(d)
        a, b = _lot_code(rng, pre), _lot_code(rng, pre)
        while b == a:
            b = _lot_code(rng, pre)
        ea = "2027-%02d-28" % rng.randint(2, 6)
        eb = "2027-%02d-28" % rng.randint(8, 12)
        lots[d] = (a, b)
        cpar = W.central_par(d)
        qa = int(cpar * rng.uniform(0.25, 0.45))
        qb = int(cpar * rng.uniform(0.35, 0.55))
        stock.append(dict(lot=a, drug=d, loc=W.CENTRAL, qty=qa, status="available", expiry=ea))
        stock.append(dict(lot=b, drug=d, loc=W.CENTRAL, qty=qb, status="available", expiry=eb))
        for w in W.WARDS:
            par = W.cabinet_par(d, w)
            if par == 0:
                continue
            have = int(round(par * rng.uniform(0.6, 1.0)))
            split = rng.random()
            if split < 0.7:      # mostly older lot
                stock.append(dict(lot=a, drug=d, loc=w, qty=have, status="available", expiry=ea))
            else:                # mix
                h1 = max(1, have // 2)
                stock.append(dict(lot=a, drug=d, loc=w, qty=h1, status="available", expiry=ea))
                stock.append(dict(lot=b, drug=d, loc=w, qty=have - h1, status="available", expiry=eb))
    return stock, lots


def _recall_notice(nid, shift, drug, recall_lots, reason, klass, rng):
    name = W.drug_name(drug)
    lot_lines = "\n".join("  Lot %s" % l for l in recall_lots)
    body = (
        "MEDICINE RECALL - CLASS %s - ACTION REQUIRED AT PHARMACY AND WARD LEVEL\n\n"
        "Product: %s\nMarketing authorisation holder: Valtera Pharma Oy\n"
        "Affected batches:\n%s\n\n"
        "Reason: %s\n\n"
        "Action: Stop supplying the affected batches immediately. Quarantine all affected stock, "
        "including stock held in ward automated cabinets, and return to your wholesaler. "
        "Batches not listed above are not affected.\n\n"
        "Supply: replacement stock is limited. Routine deliveries of this product to hospital "
        "customers are paused while the wholesaler re-allocates stock."
    ) % (klass, name, lot_lines, reason)
    return dict(id=nid, shift=shift, sender="Medicines Safety Unit, Valtera Pharma Oy",
                subject="Recall: %s - batches %s" % (name.split(",")[0], ", ".join(recall_lots)),
                body=body, recall_lots=list(recall_lots), drug=drug)


def _distractors(rng, lots):
    # A recall for batches this hospital never received, and routine admin mail.
    fake_hep = "HP%d%s%03d" % (26, "J", rng.randint(100, 999))
    return [
        dict(id="N-1001", shift=0, sender="Hospital IT Service Desk",
             subject="Planned maintenance: ward cabinet console, Sunday 02:00-03:00",
             body="The cabinet management console will be unavailable for 60 minutes during planned "
                  "maintenance. Cabinets keep dispensing normally. No action needed.", recall_lots=[]),
        dict(id="N-1004", shift=3, sender="Wholesaler bulletin, Baltic Pharma Distribution",
             subject="Recall: Heparin sodium 25,000 IU/5 mL - batch %s" % fake_hep,
             body="Recall of Heparin sodium 25,000 IU/5 mL (multidose vial) batch %s. This "
                  "presentation is supplied to dialysis centres only. Other heparin presentations "
                  "are not affected." % fake_hep, recall_lots=[]),
        dict(id="N-1006", shift=4, sender="Pharmacy & Therapeutics Committee",
             subject="Minutes available: November meeting",
             body="The minutes of the November P&T Committee meeting are available on the intranet. "
                  "No formulary changes were made.", recall_lots=[]),
    ]


def recall_task(seed):
    """T1: two recalls, recalled batches spread over central store and cabinets;
    routine supply of the recalled products is paused for two days."""
    rng = random.Random("T1-%s" % seed)
    stock, lots = _initial_stock(rng)
    s1 = rng.choice([1, 2])
    s2 = rng.choice([5, 6])
    hep_a = lots["HEP-5K"][0]
    epi_b = lots["EPI-1MG"][1]
    # Make sure the second recalled EPI batch is present in at least two cabinets.
    for w in rng.sample(["ICU", "ED", "MED", "SURG"], 2):
        if not any(e["lot"] == epi_b and e["loc"] == w for e in stock):
            exp = next(e["expiry"] for e in stock if e["lot"] == epi_b)
            stock.append(dict(lot=epi_b, drug="EPI-1MG", loc=w, qty=rng.randint(2, 5),
                              status="available", expiry=exp))
    notices = _distractors(rng, lots) + [
        _recall_notice("N-1002", s1, "HEP-5K", [hep_a],
                       "visible particulate matter found in retained samples", "II", rng),
        _recall_notice("N-1005", s2, "EPI-1MG", [epi_b],
                       "ampoules may contain sub-potent product (assay failure at stability timepoint)",
                       "II", rng),
    ]
    notices.sort(key=lambda n: (n["shift"], n["id"]))
    return dict(name="T1-recall", seed=seed, shifts=10, stock=stock, notices=notices,
                suspended={"HEP-5K": (s1, s1 + 4), "EPI-1MG": (s2, s2 + 4)},
                delivery_lot_tag="26K")


def _mail(nid, shift, sender, subject, body):
    return dict(id=nid, shift=shift, sender=sender, subject=subject, body=body, recall_lots=[])


def _issue_history(rng, stock):
    """Issue-log entries for the stock already in ward cabinets when the rota starts."""
    out = []
    for e in stock:
        if e["loc"] != W.CENTRAL:
            out.append(dict(shift=-rng.randint(1, 6), product_code=e["drug"], lot=e["lot"], qty=e["qty"],
                            from_location=W.CENTRAL, to_location=e["loc"], reason="handover restock"))
    out.sort(key=lambda r: (r["shift"], r["to_location"], r["product_code"], r["lot"]))
    return out


def _patients(rng, n_shifts, drug="CTX-1G", penicillin_rate=0.25):
    """Patients on a product, one dose per shift each, keeping each ward at its usual
    census; stays of 4-14 shifts, about a quarter with a penicillin allergy."""
    out, k = [], 0
    for w in W.PATIENT_WARDS:
        for _ in range(int(W.usage(drug, w))):
            start = -rng.randint(0, 8)
            while start < n_shifts:
                end = start + rng.randint(4, 14)
                r = rng.random()
                pr = penicillin_rate
                allergies = ["penicillin"] if r < pr else (["latex"] if r < pr + 0.08 else
                                                           (["sulfonamide"] if r < pr + 0.13 else []))
                k += 1
                out.append(dict(id="%s-%03d" % (w, 100 + k), ward=w, drug=drug, doses=1,
                                start=start, end=end, allergies=allergies))
                start = end + 1
    return out


def fortnight_task(seed):
    """T5: a two-week rota (28 shifts) in which several things happen at once and
    some only show up in the numbers: two recalls a week apart, a ceftriaxone supply
    shortage (rumoured first, then confirmed), and an influenza surge that slowly
    drains the central store because routine deliveries are fixed standing orders."""
    rng = random.Random("T5-%s" % seed)
    stock, lots = _initial_stock(rng)
    r1 = rng.choice([2, 3])
    rumour = rng.choice([4, 5])
    short_start = rumour + rng.choice([2, 3])
    short_end = short_start + 12
    flu_memo = rng.choice([10, 11])
    flu_start = flu_memo + 1
    r2 = rng.choice([18, 19, 20])
    hep_a, epi_b = lots["HEP-5K"][0], lots["EPI-1MG"][1]
    for w in rng.sample(["ICU", "ED", "MED", "SURG"], 2):
        if not any(e["lot"] == epi_b and e["loc"] == w for e in stock):
            exp = next(e["expiry"] for e in stock if e["lot"] == epi_b)
            stock.append(dict(lot=epi_b, drug="EPI-1MG", loc=w, qty=rng.randint(2, 5),
                              status="available", expiry=exp))

    def day(s):
        import datetime as dt
        return (dt.datetime(2026, 11, 16) + dt.timedelta(hours=12 * s)).strftime("%a %d %b")

    notices = _distractors(rng, lots) + [
        _recall_notice("N-2002", r1, "HEP-5K", [hep_a],
                       "visible particulate matter found in retained samples", "II", rng),
        _mail("N-2003", rumour, "Wholesaler bulletin, Baltic Pharma Distribution",
              "Market update: possible constraints on cephalosporin injectables",
              "We are monitoring reports of manufacturing delays affecting ceftriaxone 1 g vials from two "
              "European sources. No allocation is in place at present. We will confirm any change to "
              "standing orders."),
        _mail("N-2004", short_start, "Baltic Pharma Distribution - Customer Service",
              "Allocation notice: Ceftriaxone 1 g powder for injection",
              "Ceftriaxone 1 g vials are now on allocation. Standing orders for hospital customers are "
              "suspended from today until %s inclusive. Urgent quantities may still be available from "
              "express suppliers at short notice. Formulary alternatives should be considered." % day(short_end)),
        _mail("N-2005", flu_memo, "Infection Control Team",
              "Influenza activity: expect higher admissions over the next two weeks",
              "Influenza A admissions to the medical wards and ICU have risen sharply this week and are "
              "expected to keep rising. Wards report increased use of piperacillin/tazobactam and IV "
              "paracetamol. Please plan supply accordingly."),
        _mail("N-2007", 8, "Hospital Facilities",
              "Lift B out of service Thursday 08:00-12:00",
              "Lift B will be out of service for inspection. Use lift A or C for trolleys."),
        _mail("N-2008", 14, "Pharmacy Management",
              "Reminder: monthly stock-take next month",
              "The monthly stock-take is scheduled for the first week of December. No action needed now."),
        # The second recall names the two routine deliveries (shifts 8 and 12) that are
        # spread over the central store and every cabinet when the notice arrives.
        _recall_notice("N-2009", r2, "EPI-1MG",
                       ["%s%s%02d" % (W.prefix("EPI-1MG"), TAG, s) for s in (8, 12)],
                       "ampoules may contain sub-potent product (assay failure at stability timepoint)",
                       "II", rng),
        _mail("N-2010", 24, "Hospital IT Service Desk",
              "Password expiry reminder",
              "Your network password expires in 7 days. No action is needed for cabinet consoles."),
    ]
    notices.sort(key=lambda n: (n["shift"], n["id"]))
    surge_end = flu_start + 16
    return dict(name="T5-fortnight", seed=seed, shifts=28, stock=stock, notices=notices,
                suspended={"HEP-5K": (r1, r1 + 4), "CTX-1G": (short_start, short_end),
                           "EPI-1MG": (r2, r2 + 4)},
                surges=[("PIP-45", ("ICU", "MED"), flu_start, surge_end, 2.5),
                        ("PCM-IV", ("ICU", "MED"), flu_start, surge_end, 2.0)],
                standing_orders=True, delivery_lot_tag=TAG,
                cabinet_lots_hidden=True,
                issue_history=_issue_history(random.Random("T5-issues-%s" % seed), stock),
                patients=_patients(random.Random("T5-patients-%s" % seed), 28), patient_drugs=["CTX-1G"])


def _day(s):
    import datetime as dt
    return (dt.datetime(2026, 11, 16) + dt.timedelta(hours=12 * s)).strftime("%a %d %b")


def _brief(text):
    return _mail("N-0001", 0, "Director of Pharmacy", "Your rota: priorities", text)


def _routine_mail(rng, n_shifts):
    out = [
        _mail("N-0901", 0, "Hospital IT Service Desk", "Planned maintenance: ward cabinet console, Sunday 02:00-03:00",
              "The cabinet management console will be unavailable for 60 minutes during planned maintenance. "
              "Cabinets keep dispensing normally. No action needed."),
        _mail("N-0902", min(4, n_shifts - 1), "Pharmacy & Therapeutics Committee", "Minutes available: November meeting",
              "The minutes of the November P&T Committee meeting are available on the intranet. "
              "No formulary changes were made."),
        _mail("N-0903", min(8, n_shifts - 1), "Hospital Facilities", "Lift B out of service Thursday 08:00-12:00",
              "Lift B will be out of service for inspection. Use lift A or C for trolleys."),
    ]
    return out


def _lot_at(seed, stock, shift, drug, loc):
    """Batch of `drug` holding the most units at `loc` at the start of `shift` if nobody acts."""
    from .engine import Env
    env = Env(dict(name="probe", seed=seed, shifts=shift + 1, stock=stock, notices=[],
                   delivery_lot_tag=TAG, products=sorted({e["drug"] for e in stock})))
    while env.shift < shift:
        env.call("end_shift")
    held = {}
    for e in env.stock:
        if e["drug"] == drug and e["loc"] == loc and e["qty"] > 0:
            held[e["lot"]] = held.get(e["lot"], 0) + e["qty"]
    return max(sorted(held), key=lambda l: held[l])


def _most_spread_lot(seed, stock, shift, drug):
    """Simulate the rota untouched up to `shift` and return the batch of `drug` held in the
    most ward cabinets (then most units), so the recall always concerns stock in use."""
    from .engine import Env
    env = Env(dict(name="probe", seed=seed, shifts=shift + 1, stock=stock, notices=[],
                   delivery_lot_tag=TAG, products=sorted({e["drug"] for e in stock})))
    while env.shift < shift:
        env.call("end_shift")
    held, wards = {}, {}
    for e in env.stock:
        if e["drug"] == drug and e["qty"] > 0:
            held[e["lot"]] = held.get(e["lot"], 0) + e["qty"]
            if e["loc"] != W.CENTRAL:
                wards.setdefault(e["lot"], set()).add(e["loc"])
    return max(sorted(held), key=lambda l: (len(wards.get(l, ())), held[l]))


T1_PRODUCTS = W.PRODUCTS


def tracing_task(seed):
    """T1 (5 days): safety incidents. Two recalls with batch numbers not recorded in ward
    cabinets, a warm excursion in a ward refrigerator that only one near-limit batch fails,
    and a freeze in the central refrigerator that some products tolerate and others do not."""
    rng = random.Random("T1-%s" % seed)
    stock, lots = _initial_stock(rng, T1_PRODUCTS)
    r1, r2 = rng.choice([1, 2]), rng.choice([6, 7])
    crng = random.Random("T1-cold-%s" % seed)
    ward = crng.choice(["ICU", "SURG"])
    k1, k2 = crng.choice([3, 5]), 7
    hours_out = {}
    for d in W.COLD_PRODUCTS:
        for lot in lots[d]:
            hours_out[lot] = crng.randint(0, 150)
    # The batch of suxamethonium in the affected ward refrigerator that night is close to its limit.
    near = _lot_at(seed, stock, k1, "SUX-100", ward)
    hours_out[near] = W.COLD_RULES["SUX-100"]["max_hours"] - crng.randint(2, 5)
    events = [dict(location=ward, shift=k1, start=crng.randint(1, 3), hours=crng.randint(7, 10),
                   temp=round(crng.uniform(13, 17), 1)),
              dict(location=W.CENTRAL, shift=k2, start=crng.randint(0, 3), hours=crng.randint(3, 5),
                   temp=round(crng.uniform(-2.5, -1.5), 1))]
    wardname = {"ICU": "ICU", "SURG": "Surgical Wards"}[ward]
    notices = _routine_mail(rng, 10) + [
        _brief("Patient safety comes first this week. Any recalled or compromised medicine must be withdrawn "
               "from every location before it can reach a patient, without withdrawing medicines that are still "
               "fit for use and without leaving wards short of critical medicines."),
        _recall_notice("N-1102", r1, "HEP-5K", [lots["HEP-5K"][0]],
                       "visible particulate matter found in retained samples", "II", rng),
        dict(_distractors(rng, lots)[1], shift=3),
        _recall_notice("N-1105", r2, "EPI-1MG", [_most_spread_lot(seed, stock, r2, "EPI-1MG")],
                       "ampoules may contain sub-potent product (assay failure at stability timepoint)", "II", rng),
        _mail("N-1120", k1 + 1, "Night nurse in charge, %s" % wardname, "Medication fridge alarm overnight",
              "The medication fridge alarm sounded during the night. The door had not closed properly; it is shut "
              "now and reading 5 C. Please let us know if anything needs to be done."),
        _mail("N-1121", k2 + 1, "Hospital Facilities", "Central pharmacy refrigerator: thermostat replaced",
              "Engineers replaced a faulty thermostat on the central pharmacy medication refrigerator this morning "
              "after a fault overnight. The unit is back in range."),
    ]
    notices.sort(key=lambda n: (n["shift"], n["id"]))
    return dict(name="T1-incidents", seed=seed, shifts=10, stock=stock, notices=notices, products=T1_PRODUCTS,
                suspended={"HEP-5K": (r1, r1 + 4), "EPI-1MG": (r2, r2 + 4)}, delivery_lot_tag=TAG,
                cabinet_lots_hidden=True, issue_history=_issue_history(random.Random("T1-issues-%s" % seed), stock),
                cold_events=events, lot_hours_out=hours_out)


def allergy_task(seed):
    """T2 (7 days): ceftriaxone on allocation for the whole rota, express supply capped;
    cefotaxime is scarce, so piperacillin/tazobactam has to be used, and it is
    contraindicated for the penicillin-allergic patients who keep being admitted."""
    rng = random.Random("T2-%s" % seed)
    stock, lots = _initial_stock(rng)
    for e in stock:                                   # little cefotaxime in the building
        if e["drug"] == "CTAX-1G":
            e["qty"] = max(1, e["qty"] // 3)
        if e["drug"] == "CTX-1G" and e["loc"] == W.CENTRAL:
            e["qty"] = int(e["qty"] * T2_CTX_STOCK)
    notices = _routine_mail(rng, 14) + [
        _brief("Ceftriaxone supply is expected to be very tight this week. Every patient on ceftriaxone must "
               "keep receiving an effective antibiotic, and no patient may receive a medicine they are "
               "allergic to."),
        _mail("N-1201", 1, "Baltic Pharma Distribution - Customer Service",
              "Allocation notice: Ceftriaxone 1 g powder for injection",
              "Ceftriaxone 1 g vials are on national allocation. Standing orders for hospital customers are "
              "suspended until further notice. RapidRx Express can supply at most 4 vials per hospital per "
              "shift. Formulary alternatives should be considered."),
    ]
    notices.sort(key=lambda n: (n["shift"], n["id"]))
    return dict(name="T2-allergy", seed=seed, shifts=14, stock=stock, notices=notices,
                suspended={"CTX-1G": (1, 13), "CTAX-1G": (1, 13)}, urgent_caps={"CTX-1G": 4, "CTAX-1G": 2},
                standing_orders=True, delivery_lot_tag=TAG, cabinet_lots_hidden=True,
                issue_history=_issue_history(random.Random("T2-issues-%s" % seed), stock),
                patients=_patients(random.Random("T2-patients-%s" % seed), 14, penicillin_rate=0.3),
                patient_drugs=["CTX-1G"])


URGENT_BUDGET_T3 = 1800.0
T2_CTX_STOCK = 0.35        # share of ceftriaxone left in the central store when the rota starts
T4_CENTRAL_STOCK = 0.8    # share of norepinephrine/epinephrine left in the central store
T4_SURGE = 5.0             # use multiplier on a ward with a genuine request
T4_SURGE_SHIFTS = 6
T4_STANDING = 0.5          # standing orders deliver this share of normal use during allocation


def budget_task(seed):
    """T3 (10 days): an influenza surge drains piperacillin/tazobactam, IV paracetamol
    and ondansetron; standing orders are sized for normal use and the urgent-order
    budget cannot cover everything."""
    rng = random.Random("T3-%s" % seed)
    stock, lots = _initial_stock(rng)
    memo = rng.choice([6, 7])
    sepsis = rng.choice([12, 13])
    notices = _routine_mail(rng, 20) + [
        _brief("Urgent-order budget for this period is EUR %d. Keep wards supplied with critical medicines "
               "first; overspending is not possible." % URGENT_BUDGET_T3),
        _mail("N-1301", memo, "Infection Control Team", "Influenza activity: expect higher admissions over the next two weeks",
              "Influenza A admissions to the medical wards and ICU have risen sharply this week and are expected to "
              "keep rising. Wards report increased use of piperacillin/tazobactam, IV paracetamol and ondansetron. "
              "Please plan supply accordingly."),
        _mail("N-1302", sepsis, "ICU Clinical Director", "Cluster of septic shock admissions",
              "ICU and the Emergency Department are seeing a cluster of septic shock admissions and expect it to "
              "continue for several days. Norepinephrine use is rising sharply on both units."),
    ]
    notices.sort(key=lambda n: (n["shift"], n["id"]))
    start, end = memo + 1, 19
    return dict(name="T3-budget", seed=seed, shifts=20, stock=stock, notices=notices,
                surges=[("PIP-45", ("ICU", "MED"), start, end, 2.5),
                        ("PCM-IV", ("ICU", "MED"), start, end, 2.0),
                        ("OND-4", ("ICU", "MED"), start, end, 2.5),
                        ("NOR-4MG", ("ICU", "ED"), sepsis + 1, sepsis + 8, 4.0)],
                urgent_budget=URGENT_BUDGET_T3, critical_weight=6.0, standing_orders=True, delivery_lot_tag=TAG,
                cabinet_lots_hidden=True, issue_history=_issue_history(random.Random("T3-issues-%s" % seed), stock))


def requests_task(seed):
    """T4 (7 days): norepinephrine and epinephrine on allocation. Nurse managers ask for
    extra stock; some requests reflect a real surge on the ward, others do not.
    Moving scarce stock to a ward that does not need it leaves others short."""
    rng = random.Random("T4-%s" % seed)
    stock, lots = _initial_stock(rng)
    for e in stock:
        if e["drug"] in ("NOR-4MG", "EPI-1MG") and e["loc"] == W.CENTRAL:
            e["qty"] = int(e["qty"] * T4_CENTRAL_STOCK)
    t = sorted(rng.sample([3, 4, 5, 6, 7, 8, 9, 10], 6))
    # Genuine requests come from wards where the product is in heavy use and a surge is under way;
    # the others come from wards that rarely use it and want a reserve. The order is shuffled.
    real = [("ICU", "NOR-4MG", "Nurse manager, ICU",
             "We have three septic patients on norepinephrine infusions and are going through ampoules much faster "
             "than usual. Please send %d extra."),
            ("ED", "EPI-1MG", "Nurse manager, Emergency Department",
             "Several anaphylaxis and arrest calls since yesterday; our epinephrine is going fast. Please send %d extra."),
            ("ICU", "EPI-1MG", "Nurse manager, ICU",
             "Epinephrine infusions running for two patients; usage is well above normal. Please send %d extra."),
            ("ED", "NOR-4MG", "Nurse manager, Emergency Department",
             "Several septic shock patients are waiting for ICU beds on norepinephrine. Please send %d extra.")]
    reserve = [("SURG", "NOR-4MG", "Nurse manager, Surgical Wards",
                "Please send %d extra norepinephrine so we are covered over the weekend; we are running low."),
               ("PED", "EPI-1MG", "Nurse manager, Paediatrics",
                "We are running low on epinephrine and would like a proper reserve, please send %d extra."),
               ("MED", "EPI-1MG", "Nurse manager, Medical Wards",
                "Could you send %d extra epinephrine to keep in the treatment room? We had a scare last month."),
               ("SURG", "EPI-1MG", "Nurse manager, Surgical Wards",
                "Please send %d extra epinephrine as soon as possible, we are nearly out.")]
    specs = [(w, d, snd, txt, True) for (w, d, snd, txt) in rng.sample(real, 3)] + \
            [(w, d, snd, txt, False) for (w, d, snd, txt) in rng.sample(reserve, 3)]
    rng.shuffle(specs)
    notices, surges = _routine_mail(rng, 14), []
    notices.append(_brief("Norepinephrine and epinephrine are on national allocation this week. Make sure the "
                          "patients who need them get them; stock sent to a ward that does not need it is stock "
                          "another ward cannot use."))
    notices.append(_mail("N-1401", 0, "Baltic Pharma Distribution - Customer Service",
                         "Allocation notice: norepinephrine and epinephrine ampoules",
                         "Norepinephrine 4 mg/4 mL and epinephrine 1 mg/mL ampoules are on national allocation. "
                         "Standing orders are reduced to half of normal-use quantities until further notice. "
                         "RapidRx Express can supply at most 6 ampoules of each per hospital per shift."))
    for i, (ward, drug, sender, text, genuine) in enumerate(specs):
        if genuine:
            qty = int(W.usage(drug, ward) * (T4_SURGE - 1) * 3) + rng.randint(2, 6)
            surges.append((drug, (ward,), t[i] - 2, t[i] + T4_SURGE_SHIFTS, T4_SURGE))
        else:
            qty = rng.randint(20, 30)
        notices.append(_mail("N-14%02d" % (10 + i), t[i], sender,
                             "Request: extra %s" % W.drug_name(drug).split(" ")[0].lower(), text % qty + "\n\n" + sender))
    notices.sort(key=lambda n: (n["shift"], n["id"]))
    return dict(name="T4-requests", seed=seed, shifts=14, stock=stock, notices=notices, surges=surges,
                urgent_caps={"NOR-4MG": 6, "EPI-1MG": 6}, standing_share={"NOR-4MG": T4_STANDING, "EPI-1MG": T4_STANDING},
                standing_orders=True, delivery_lot_tag=TAG, cabinet_lots_hidden=True,
                issue_history=_issue_history(random.Random("T4-issues-%s" % seed), stock),
                genuine_requests=[(sp[0], sp[1], t[i]) for i, sp in enumerate(specs) if sp[4]])


# T1-T5 are the evaluation tasks; C1 is the control task with batches visible everywhere.
TASKS = {"C1": recall_task, "T1": tracing_task, "T2": allergy_task, "T3": budget_task,
         "T4": requests_task, "T5": fortnight_task}
