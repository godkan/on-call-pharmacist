"""Task generators. Each returns a task dict for engine.Env."""
import random

from . import world as W


def _lot_code(rng, prefix):
    return "%s%d%s%03d" % (prefix, rng.choice([24, 25]), rng.choice("ABCDEFGH"), rng.randint(100, 999))


def _initial_stock(rng):
    """Two lots per product: an older one (A) and a newer one (B). Cabinets mostly
    hold the older lot because they were filled from central earlier."""
    stock, lots = [], {}
    for d in W.DRUGS:
        pre = W.DRUGS[d][4]
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
        _recall_notice("N-2009", r2, "EPI-1MG", [epi_b],
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
                standing_orders=True, delivery_lot_tag="26K")


TASKS = {"T1": recall_task, "T5": fortnight_task}
