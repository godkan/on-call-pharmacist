"""Hospital pharmacy simulation: lots spread over a central store and ward
cabinets, ward consumption, automatic replenishment, notices, and the tools
the on-duty pharmacist uses.

Determinism: ward demand is drawn from an RNG keyed only by (seed, shift,
ward, drug), so it never depends on the actions taken. The same task, seed
and action sequence always reproduce the same episode.
"""
import datetime as dt
import math
import random

from . import world as W

SHIFT_MINUTES = 120
START = dt.datetime(2026, 11, 16, 7, 0)

TOOL_MINUTES = {
    "get_status": 0,
    "read_notices": 5,
    "read_policy": 5,
    "get_drug_info": 5,
    "list_inventory": 5,
    "find_lot": 5,
    "get_usage_report": 5,
    "get_issue_log": 5,
    "list_patients": 5,
    "inspect_cabinet": 15,
    "revoke_substitution": 5,
    "list_approvals": 5,
    "quarantine_lot": 10,
    "transfer_stock": 10,
    "approve_substitution": 10,
    "place_urgent_order": 15,
    "end_shift": 0,
}

POLICIES = {
    "recall": (
        "SOP-PH-07 Medicine recalls\n"
        "1. On receipt of a recall notice, identify every location holding an affected lot: the central "
        "store and all ward automated cabinets.\n"
        "2. Quarantine all affected stock the same shift. Quarantined stock is withdrawn from use and is "
        "collected by the wholesaler; do not dispose of it.\n"
        "3. Only the lot numbers named in the notice are affected. Do not withdraw other lots of the "
        "same product.\n"
        "4. Withdrawing stock must not leave a ward without a critical medicine: arrange replacement "
        "supply (transfer, urgent order, or an approved alternative) before the next round.\n"
        "5. Recheck affected lots on following shifts until all have been withdrawn."
    ),
    "shortage": (
        "SOP-PH-11 Medicine shortages\n"
        "Ward cabinets are restocked automatically from the central store at the end of each shift "
        "(to par level) and the central store receives routine wholesaler deliveries every second day. "
        "When routine supply is interrupted, the on-duty pharmacist may transfer stock between "
        "locations, place urgent orders with RapidRx Express (delivered at the start of the next "
        "shift, 40% surcharge), or approve a formulary alternative for a ward. Allocation priority "
        "under policy P-12: ICU and ED first, then other wards."
    ),
    "substitution": (
        "SOP-PH-12 Therapeutic substitution\n"
        "Only alternatives on the P&T Committee formulary list F-3 may be approved. An approval "
        "applies to one ward and one product and lets the ward cabinet issue the alternative when "
        "the original product is out of stock. Use get_drug_info to see approved alternatives."
    ),
    "ward_requests": (
        "SOP-PH-16 Ward requests for extra stock\n"
        "Ward cabinets are restocked to par automatically. A request for stock above par should be "
        "checked against the ward's recent usage and current cabinet stock before it is met: meet "
        "requests that the data support, and do not move scarce stock to a ward that does not need it, "
        "because it is then unavailable to other wards. Stock can be transferred back."
    ),
    "urgent_order": (
        "SOP-PH-14 Urgent orders\n"
        "Urgent orders go to RapidRx Express, arrive at the central store at the start of the next "
        "shift and cost list price plus 40%. Order what is needed to bridge the gap; overstock "
        "ties up budget."
    ),
}


POLICIES_V3_URGENT = (
    "SOP-PH-14 Urgent orders\n"
    "Urgent orders go to RapidRx Express, arrive at the central store at the start of the next "
    "shift and cost list price plus 40%. During a national shortage RapidRx may limit the quantity "
    "per product per shift (shown in get_drug_info). Urgent spending this rota is limited to the "
    "budget shown in get_status; orders beyond it are refused. Order what is needed to bridge the "
    "gap and keep budget for critical medicines."
)

POLICIES_V3 = {
    "recall": (
        "SOP-PH-07 Medicine recalls\n"
        "1. On receipt of a recall notice, identify every location holding an affected lot: the central "
        "store and all ward automated cabinets. Ward cabinets record products and quantities but not batch "
        "numbers. The central store issue log shows which batches were sent to which cabinet and when; a "
        "pharmacist can also inspect a cabinet on site.\n"
        "2. Quarantine all affected stock the same shift. Quarantining at a ward cabinet means a pharmacist "
        "goes to the ward and removes the batch. Quarantined stock is collected by the wholesaler; do not "
        "dispose of it.\n"
        "3. Only the lot numbers named in the notice are affected. Do not withdraw other lots of the "
        "same product.\n"
        "4. Withdrawing stock must not leave a ward without a critical medicine: arrange replacement "
        "supply (transfer, urgent order, or an approved alternative) before the next round.\n"
        "5. Recheck affected lots on following shifts until all have been withdrawn."
    ),
    "substitution": (
        "SOP-PH-12 Therapeutic substitution\n"
        "Only alternatives on the P&T Committee formulary list F-3 may be approved. A ward-level approval "
        "lets the ward cabinet issue the alternative to any patient on that ward when the original product "
        "is out of stock. Some alternatives carry a restriction (for example a contraindication in a drug "
        "allergy): these must not be approved ward-wide while any patient on the ward has that allergy; "
        "approve them for individual patients after checking the patient list. Use get_drug_info to see "
        "approved alternatives and restrictions, and list_patients to see patients and allergies."
    ),
}


def poisson(rng, mean):
    if mean <= 0:
        return 0
    l, k, p = math.exp(-mean), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


class Env:
    def __init__(self, task):
        self.task = task
        self.seed = task["seed"]
        self.n_shifts = task["shifts"]
        self.shift = 0
        self.minutes_left = SHIFT_MINUTES
        self.done = False
        # stock entries: dict(lot, drug, loc, qty, status, expiry)
        self.stock = [dict(e) for e in task["stock"]]
        self.notices = task["notices"]
        self.read_ids = set()
        self.suspended = task.get("suspended", {})
        self.substitutions = set()   # (ward, drug, alt)
        self.pending_orders = []     # (arrive_shift, drug, qty, lot)
        self.order_seq = 0
        self.usage_log = []          # dicts per shift/ward/drug/lot
        self.attended = set()
        self.handover_note = ""
        self.hidden_lots = bool(task.get("cabinet_lots_hidden"))
        self.issue_log = [dict(e) for e in task.get("issue_history", [])]   # central -> cabinet movements
        self.patients = task.get("patients", [])
        self.patient_drugs = set(task.get("patient_drugs", []))
        self.patient_subs = set()    # (patient_id, drug, alt)
        self.urgent_caps = task.get("urgent_caps", {})      # product -> max units per shift
        self.budget = task.get("urgent_budget")             # EUR for urgent orders, or None
        self.ordered_this_shift = {}
        self.metrics = {
            "recalled_given": 0,          # units of recalled lots given after the notice
            "shortfall": {},              # (ward, drug) -> units not available
            "wrong_quarantine_units": 0,
            "urgent_spend": 0.0,
            "urgent_premium": 0.0,
            "missed_shifts": 0,
            "contraindicated_given": 0,   # doses of an alternative given to a patient allergic to it
        }
        if "critical_weight" in task:
            self.metrics["critical_weight"] = task["critical_weight"]

    # ---------- helpers ----------
    def now(self):
        return START + dt.timedelta(hours=12 * self.shift)

    def shift_label(self, s=None):
        s = self.shift if s is None else s
        t = START + dt.timedelta(hours=12 * s)
        return "%s %s shift" % (t.strftime("%a %d %b %Y"), "day" if s % 2 == 0 else "night")

    def recalled_lots(self, upto_shift=None):
        upto = self.shift if upto_shift is None else upto_shift
        out = {}
        for n in self.notices:
            if n["shift"] <= upto:
                for lot in n.get("recall_lots", []):
                    out[lot] = n["shift"]
        return out

    def _available(self, drug, loc):
        lots = [e for e in self.stock if e["drug"] == drug and e["loc"] == loc
                and e["status"] == "available" and e["qty"] > 0]
        return sorted(lots, key=lambda e: (e["expiry"], e["lot"]))   # FEFO

    def _qty(self, drug, loc):
        return sum(e["qty"] for e in self._available(drug, loc))

    def _move(self, drug, src, dst, qty, reason="transfer"):
        moved = 0
        for e in self._available(drug, src):
            if moved >= qty:
                break
            take = min(e["qty"], qty - moved)
            e["qty"] -= take
            moved += take
            self._add(e["lot"], drug, dst, take, e["expiry"])
            self.issue_log.append(dict(shift=self.shift, product_code=drug, lot=e["lot"], qty=take,
                                       from_location=src, to_location=dst, reason=reason))
        return moved

    def _add(self, lot, drug, loc, qty, expiry, status="available"):
        for e in self.stock:
            if e["lot"] == lot and e["loc"] == loc and e["status"] == status:
                e["qty"] += qty
                return
        self.stock.append(dict(lot=lot, drug=drug, loc=loc, qty=qty, status=status, expiry=expiry))

    # ---------- world dynamics ----------
    def _consume(self):
        s = self.shift
        recalled = self.recalled_lots()
        self._consume_patients(recalled)
        for ward in W.WARDS:
            for drug in W.DRUGS:
                if drug in self.patient_drugs:
                    continue
                rng = random.Random("%s-%d-%s-%s" % (self.seed, s, ward, drug))
                need = poisson(rng, W.usage(drug, ward) * self._multiplier(drug, ward, s))
                if need == 0:
                    continue
                need = self._draw(ward, drug, need, recalled, s)
                if need > 0:
                    for (w, d, alt) in sorted(self.substitutions):
                        if w == ward and d == drug and need > 0:
                            need = self._draw(ward, alt, need, recalled, s, as_sub_for=drug)
                if need > 0:
                    k = (ward, drug)
                    self.metrics["shortfall"][k] = self.metrics["shortfall"].get(k, 0) + need
                    self.usage_log.append(dict(shift=s, ward=ward, drug=drug, lot=None, qty=0, unmet=need))

    def active_patients(self, ward=None, drug=None, s=None):
        s = self.shift if s is None else s
        return [p for p in self.patients if p["start"] <= s <= p["end"]
                and (ward is None or p["ward"] == ward) and (drug is None or p["drug"] == drug)]

    def _consume_patients(self, recalled):
        """Drugs given per patient: original product first, then an alternative approved
        for that patient, then any ward-level approved alternative."""
        s = self.shift
        for p in sorted(self.active_patients(), key=lambda p: p["id"]):
            need = self._draw(p["ward"], p["drug"], p["doses"], recalled, s, patient=p["id"])
            alts = [a for (pid, d, a) in sorted(self.patient_subs) if pid == p["id"] and d == p["drug"]]
            alts += [a for (w, d, a) in sorted(self.substitutions) if w == p["ward"] and d == p["drug"]]
            for alt in alts:
                if need == 0:
                    break
                before = need
                need = self._draw(p["ward"], alt, need, recalled, s, as_sub_for=p["drug"], patient=p["id"])
                if W.RESTRICTIONS.get(alt) in p["allergies"]:
                    self.metrics["contraindicated_given"] += before - need
            if need > 0:
                k = (p["ward"], p["drug"])
                self.metrics["shortfall"][k] = self.metrics["shortfall"].get(k, 0) + need
                self.usage_log.append(dict(shift=s, ward=p["ward"], drug=p["drug"], lot=None, qty=0,
                                           unmet=need, patient=p["id"]))

    def _multiplier(self, drug, ward, s):
        m = 1.0
        for (d, wards, start, end, mult) in self.task.get("surges", []):
            if d == drug and ward in wards and start <= s <= end:
                m *= mult
        return m

    def _draw(self, ward, drug, need, recalled, s, as_sub_for=None, patient=None):
        for e in self._available(drug, ward):
            if need == 0:
                break
            take = min(e["qty"], need)
            e["qty"] -= take
            need -= take
            self.usage_log.append(dict(shift=s, ward=ward, drug=drug, lot=e["lot"], qty=take,
                                       unmet=0, substitute_for=as_sub_for, patient=patient))
            if e["lot"] in recalled and recalled[e["lot"]] <= s:
                self.metrics["recalled_given"] += take
        return need

    def _restock_cabinets(self):
        for ward in W.WARDS:
            for drug in W.DRUGS:
                gap = W.cabinet_par(drug, ward) - self._qty(drug, ward)
                if gap > 0:
                    self._move(drug, W.CENTRAL, ward, gap, reason="handover restock")

    def _deliveries(self):
        s = self.shift
        for o in list(self.pending_orders):
            if o[0] == s:
                _, drug, qty, lot = o
                self._add(lot, drug, W.CENTRAL, qty, "2028-06-30")
                self.pending_orders.remove(o)
        if s % W.DELIVERY_EVERY_SHIFTS == 0 and s > 0:
            for drug in W.DRUGS:
                sus = self.suspended.get(drug)
                if sus and sus[0] <= s <= sus[1]:
                    continue
                gap = W.central_par(drug) - self._qty(drug, W.CENTRAL)
                if self.task.get("standing_orders"):
                    # Fixed standing order sized for normal use (scaled down under allocation); capped at par.
                    share = self.task.get("standing_share", {}).get(drug, 1.0)
                    gap = min(gap, int(W.DELIVERY_EVERY_SHIFTS * W.total_usage(drug) * share))
                if gap > 0:
                    lot = "%s%s%02d" % (W.DRUGS[drug][4], self.task["delivery_lot_tag"], s)
                    self._add(lot, drug, W.CENTRAL, gap, "2028-03-31")

    def _advance(self):
        self._consume()
        self._restock_cabinets()
        self.shift += 1
        self.minutes_left = SHIFT_MINUTES
        self.ordered_this_shift = {}
        if self.shift >= self.n_shifts:
            self.done = True
            return
        self._deliveries()

    def run_to_end(self):
        """Used when an agent stops early: remaining shifts run unattended."""
        while not self.done:
            if self.shift not in self.attended:
                self.metrics["missed_shifts"] += 1
            self._advance()

    # ---------- tools ----------
    def call(self, name, args=None):
        args = args or {}
        if self.done:
            return {"error": "The rota period has ended."}
        if name not in TOOL_MINUTES:
            return {"error": "Unknown function %s." % name}
        cost = TOOL_MINUTES[name]
        if cost > self.minutes_left:
            return {"error": "Not enough time left this shift (%d min left, %s takes %d min). "
                             "Call end_shift to hand over." % (self.minutes_left, name, cost)}
        if name != "end_shift":
            self.attended.add(self.shift)
        try:
            result = getattr(self, "t_" + name)(**args)
        except TypeError as ex:
            return {"error": "Invalid arguments for %s: %s" % (name, ex)}
        if "error" not in result:
            self.minutes_left -= cost
        return result

    def t_get_status(self):
        unread = [n for n in self.notices if n["shift"] <= self.shift and n["id"] not in self.read_ids]
        return {"hospital": W.HOSPITAL, "shift": self.shift_label(), "shift_number": self.shift + 1,
                "shifts_in_rota": self.n_shifts, "minutes_left_this_shift": self.minutes_left,
                "unread_notices": len(unread),
                **({"urgent_order_budget_left_eur": round(self.budget - self.metrics["urgent_spend"], 2)}
                   if self.budget is not None else {})}

    def t_read_notices(self, include_read=False):
        out = []
        for n in self.notices:
            if n["shift"] <= self.shift and (include_read or n["id"] not in self.read_ids):
                out.append({"id": n["id"], "received": self.shift_label(n["shift"]),
                            "from": n["sender"], "subject": n["subject"], "body": n["body"]})
                self.read_ids.add(n["id"])
        return {"notices": out}

    def t_read_policy(self, topic):
        if topic not in POLICIES:
            return {"error": "Unknown topic. Available: %s" % ", ".join(POLICIES)}
        if topic == "urgent_order" and (self.urgent_caps or self.budget is not None):
            return {"policy": POLICIES_V3_URGENT}
        if self.hidden_lots or self.patients:
            return {"policy": POLICIES_V3.get(topic, POLICIES[topic])}
        return {"policy": POLICIES[topic]}

    def t_get_drug_info(self, product_code):
        d = product_code
        if d not in W.DRUGS:
            return {"error": "Unknown product code. Known codes: %s" % ", ".join(W.DRUGS)}
        sus = self.suspended.get(d)
        status = "normal"
        if sus and sus[0] <= self.shift <= sus[1]:
            status = "routine deliveries suspended until %s" % self.shift_label(sus[1] + 1)
        return {"product_code": d, "name": W.drug_name(d), "critical_medicine": W.critical(d),
                "unit_price_eur": W.price(d), "approved_alternatives": W.ALTERNATIVES.get(d, []),
                "alternative_restrictions": {a: "contraindicated in %s allergy; approve per patient only"
                                             % W.RESTRICTIONS[a] for a in W.ALTERNATIVES.get(d, [])
                                             if a in W.RESTRICTIONS},
                "routine_supply": status, "central_par": W.central_par(d),
                **({"urgent_order_limit_per_shift": self.urgent_caps[d]} if d in self.urgent_caps else {}),
                "ward_par": {w: W.cabinet_par(d, w) for w in W.WARDS}}

    def t_list_inventory(self, location, product_code=None):
        if location not in W.LOCATIONS:
            return {"error": "Unknown location. Use one of %s" % ", ".join(W.LOCATIONS)}
        rows = [e for e in self.stock if e["loc"] == location and e["qty"] > 0
                and (product_code is None or e["drug"] == product_code)]
        rows.sort(key=lambda e: (e["drug"], e["expiry"], e["lot"]))
        if self.hidden_lots and location != W.CENTRAL:
            agg, out = {}, []
            for e in rows:
                if e["status"] == "available":
                    agg[e["drug"]] = agg.get(e["drug"], 0) + e["qty"]
                else:
                    out.append({"product_code": e["drug"], "lot": e["lot"], "qty": e["qty"], "status": e["status"]})
            out = [{"product_code": d, "lot": "not recorded by cabinet", "qty": q, "status": "available"}
                   for d, q in sorted(agg.items())] + out
            return {"location": W.LOCATION_NAMES[location], "stock": out,
                    "note": "Ward cabinets do not record batch numbers. See get_issue_log or inspect_cabinet."}
        return {"location": W.LOCATION_NAMES[location],
                "stock": [{"product_code": e["drug"], "lot": e["lot"], "expiry": e["expiry"],
                           "qty": e["qty"], "status": e["status"]} for e in rows]}

    def t_find_lot(self, lot):
        rows = [e for e in self.stock if e["lot"].upper() == lot.strip().upper() and e["qty"] > 0]
        if self.hidden_lots:
            rows = [e for e in rows if e["loc"] == W.CENTRAL or e["status"] != "available"]
            return {"lot": lot, "locations": [{"location": e["loc"], "product_code": e["drug"],
                                               "qty": e["qty"], "status": e["status"]} for e in rows],
                    "note": "Searches the central store and quarantine records only; ward cabinets do not "
                            "record batch numbers. See get_issue_log."}
        return {"lot": lot, "locations": [{"location": e["loc"], "product_code": e["drug"],
                                           "qty": e["qty"], "status": e["status"]} for e in rows]}

    def t_get_issue_log(self, product_code, lot=None):
        if product_code not in W.DRUGS:
            return {"error": "Unknown product code."}
        rows = [r for r in self.issue_log if r["product_code"] == product_code
                and (lot is None or r["lot"].upper() == str(lot).strip().upper())]
        rows = rows[-60:]
        return {"product_code": product_code, "entries": [
            {"when": self.shift_label(r["shift"]) if r["shift"] >= 0 else
             (START + dt.timedelta(hours=12 * r["shift"])).strftime("%a %d %b %Y") + " (before rota)",
             "lot": r["lot"], "qty": r["qty"], "from": r["from_location"], "to": r["to_location"],
             "reason": r["reason"]} for r in rows],
            "note": "Most recent 60 movements, oldest first. Ward use is not recorded by batch."}

    def t_inspect_cabinet(self, ward, product_code):
        if ward not in W.WARDS or product_code not in W.DRUGS:
            return {"error": "Unknown ward or product code."}
        rows = [e for e in self.stock if e["loc"] == ward and e["drug"] == product_code and e["qty"] > 0]
        return {"ward": ward, "product_code": product_code,
                "found": [{"lot": e["lot"], "expiry": e["expiry"], "qty": e["qty"], "status": e["status"]}
                          for e in sorted(rows, key=lambda e: e["lot"])]}

    def t_list_patients(self, ward, product_code=None):
        if ward not in W.WARDS:
            return {"error": "Unknown ward."}
        pts = self.active_patients(ward=ward, drug=product_code)
        return {"ward": ward, "patients": [
            {"patient_id": p["id"], "on": p["drug"], "doses_per_shift": p["doses"],
             "allergies": p["allergies"] or ["none known"], "since": self.shift_label(max(p["start"], 0))
             if p["start"] >= 0 else "before rota"} for p in sorted(pts, key=lambda p: p["id"])]}

    def t_get_usage_report(self, location, product_code=None):
        if location not in W.WARDS:
            return {"error": "Usage reports exist for ward cabinets: %s" % ", ".join(W.WARDS)}
        rows = {}
        for u in self.usage_log:
            if u["ward"] == location and u["shift"] >= self.shift - 4 and \
                    (product_code is None or u["drug"] == product_code):
                k = (u["shift"], u["drug"])
                r = rows.setdefault(k, {"shift": self.shift_label(u["shift"]), "product_code": u["drug"],
                                        "issued": 0, "could_not_issue": 0})
                r["issued"] += u["qty"]
                r["could_not_issue"] += u["unmet"]
        return {"ward": location, "last_shifts": list(rows.values())}

    def t_quarantine_lot(self, lot, location):
        hits = [e for e in self.stock if e["lot"].upper() == lot.strip().upper() and e["loc"] == location
                and e["status"] == "available" and e["qty"] > 0]
        if not hits:
            if self.hidden_lots and location in W.WARDS:
                return {"ok": True, "quarantined_units": 0, "lot": lot, "location": location,
                        "note": "Pharmacist checked the cabinet: no units of this batch found."}
            return {"error": "No available stock of lot %s at %s." % (lot, location)}
        recalled = self.recalled_lots()
        n = 0
        for e in hits:
            qty = e["qty"]
            e["qty"] = 0
            self._add(e["lot"], e["drug"], location, qty, e["expiry"], status="quarantined")
            n += qty
            if e["lot"] not in recalled:
                self.metrics["wrong_quarantine_units"] += qty
        return {"ok": True, "quarantined_units": n, "lot": lot, "location": location}

    def t_transfer_stock(self, product_code, from_location, to_location, qty):
        if product_code not in W.DRUGS or from_location not in W.LOCATIONS or to_location not in W.LOCATIONS:
            return {"error": "Unknown product code or location."}
        qty = int(qty)
        if qty <= 0 or from_location == to_location:
            return {"error": "Quantity must be positive and locations different."}
        moved = self._move(product_code, from_location, to_location, qty)
        return {"ok": True, "moved_units": moved, "note": "" if moved == qty else
                "only %d available units at %s" % (moved, from_location)}

    def t_approve_substitution(self, ward, product_code, alternative_code, patient_id=None):
        if alternative_code not in W.ALTERNATIVES.get(product_code, []):
            return {"error": "%s is not an approved alternative for %s." % (alternative_code, product_code)}
        if ward not in W.WARDS:
            return {"error": "Unknown ward."}
        if patient_id:
            p = [p for p in self.active_patients(ward=ward, drug=product_code) if p["id"] == patient_id]
            if not p:
                return {"error": "No current patient %s on %s in %s." % (patient_id, product_code, ward)}
            self.patient_subs.add((patient_id, product_code, alternative_code))
            return {"ok": True, "scope": "patient %s" % patient_id}
        self.substitutions.add((ward, product_code, alternative_code))
        return {"ok": True, "scope": "all patients on %s" % ward}

    def t_revoke_substitution(self, ward, product_code, alternative_code, patient_id=None):
        key = (patient_id, product_code, alternative_code) if patient_id else (ward, product_code, alternative_code)
        pool = self.patient_subs if patient_id else self.substitutions
        if key not in pool:
            return {"error": "No such approval is active."}
        pool.discard(key)
        return {"ok": True}

    def t_list_approvals(self, ward=None):
        return {"ward_level": [{"ward": w, "product_code": d, "alternative_code": a}
                               for (w, d, a) in sorted(self.substitutions) if ward in (None, w)],
                "patient_level": [{"patient_id": pid, "product_code": d, "alternative_code": a}
                                  for (pid, d, a) in sorted(self.patient_subs)
                                  if ward is None or any(p["id"] == pid and p["ward"] == ward for p in self.patients)]}

    def t_place_urgent_order(self, product_code, qty):
        if product_code not in W.DRUGS:
            return {"error": "Unknown product code."}
        qty = int(qty)
        if qty <= 0 or qty > 3 * W.central_par(product_code):
            return {"error": "Quantity must be between 1 and %d." % (3 * W.central_par(product_code))}
        cap = self.urgent_caps.get(product_code)
        if cap is not None and self.ordered_this_shift.get(product_code, 0) + qty > cap:
            return {"error": "RapidRx allocation: at most %d units of %s per shift (%d already ordered "
                             "this shift)." % (cap, product_code, self.ordered_this_shift.get(product_code, 0))}
        cost = qty * W.price(product_code) * (1 + W.EMERGENCY_MARKUP)
        if self.budget is not None and self.metrics["urgent_spend"] + cost > self.budget + 1e-9:
            return {"error": "Urgent-order budget exceeded: EUR %.2f left, order costs EUR %.2f."
                             % (self.budget - self.metrics["urgent_spend"], cost)}
        self.ordered_this_shift[product_code] = self.ordered_this_shift.get(product_code, 0) + qty
        self.order_seq += 1
        lot = "RX%s%s%02d" % (W.DRUGS[product_code][4], self.task["delivery_lot_tag"], self.order_seq)
        self.pending_orders.append((self.shift + 1, product_code, qty, lot))
        self.metrics["urgent_spend"] += cost
        self.metrics["urgent_premium"] += qty * W.price(product_code) * W.EMERGENCY_MARKUP
        return {"ok": True, "order_ref": "RRX-%04d" % (self.order_seq + 4100),
                "arrives": self.shift_label(self.shift + 1), "cost_eur": round(cost, 2)}

    def t_end_shift(self, handover_note=""):
        if self.shift not in self.attended:
            self.metrics["missed_shifts"] += 1
        self.handover_note = str(handover_note or "")[:4000]
        self._advance()
        if self.done:
            return {"ok": True, "message": "Rota complete. Thank you."}
        return {"ok": True, "now": self.shift_label(), "minutes_available": SHIFT_MINUTES}
