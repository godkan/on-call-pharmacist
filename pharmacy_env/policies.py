"""Scripted anchor policies. They act only through Env.call, exactly like an agent,
and read recall information from the notice text."""
import re

from . import world as W

LOT_RE = re.compile(r"^\s*Lot\s+([A-Z0-9]+)\s*$", re.M)


def _recall_lots_from(notices):
    out = []
    for n in notices:
        if "Affected batches" in n["body"]:
            out += LOT_RE.findall(n["body"])
    return out


class RecallTracker:
    """Where a recalled batch may be. Uses find_lot for the central store and, when
    cabinets do not record batches, the issue log to see which cabinets received it.
    A cabinet counts as done only after a successful visit, and is visited again only
    if the log later shows new issues of the batch to it. A batch with nothing left
    to do is closed and no longer rechecked."""

    def __init__(self, env):
        self.env, self.lots, self.done, self.closed, self.cache = env, {}, {}, set(), {}

    def register(self, notice):
        drugs = _drugs_named(notice["subject"])
        for lot in _recall_lots_from([notice]):
            d = drugs[0] if drugs else None
            found = self._look(lot, d)
            if found:
                self.lots[lot] = d
                self.cache[lot] = found

    def _look(self, lot, drug):
        out = []
        for r in self.env.call("find_lot", {"lot": lot}).get("locations", []):
            if r["status"] == "available":
                out.append((r["location"], None))      # seen directly: always act on it
        if self.env.hidden_lots and drug:
            counts = {}
            for e in self.env.call("get_issue_log", {"product_code": drug, "lot": lot}).get("entries", []):
                if e["to"] in W.WARDS:
                    counts[e["to"]] = counts.get(e["to"], 0) + 1
            out += sorted(counts.items())
        return out

    def places(self, lot, drug):
        found = self.cache.pop(lot, None)
        if found is None:
            found = self._look(lot, drug)
        return [(w, c) for w, c in found if c is None or c > self.done.get((lot, w), 0)]

    def withdraw(self):
        hits = []
        for lot, drug in sorted(self.lots.items()):
            if lot in self.closed:
                continue
            todo = self.places(lot, drug)
            if not todo:
                self.closed.add(lot)
            for where, count in todo:
                rank = -1e9 if where == W.CENTRAL else -W.usage(drug, where)
                hits.append((rank, where, lot, count))
        for _, where, lot, count in sorted(hits):
            r = self.env.call("quarantine_lot", {"lot": lot, "location": where})
            if "ok" in r and count is not None:
                self.done[(lot, where)] = count


WARD_BY_SENDER = {"ICU": "ICU", "Emergency Department": "ED", "Surgical Wards": "SURG",
                  "Medical Wards": "MED", "Paediatrics": "PED"}


def _request(notice):
    """(ward, product, qty) from a nurse manager's request, or None."""
    if not notice["from"].startswith("Nurse manager"):
        return None
    ward = next((w for k, w in WARD_BY_SENDER.items() if notice["from"].endswith(k)), None)
    text = (notice["subject"] + " " + notice["body"]).lower()
    drug = "NOR-4MG" if "norepinephrine" in text else ("EPI-1MG" if "epinephrine" in text else None)
    m = re.search(r"send (\d+)", notice["body"])
    return (ward, drug, int(m.group(1))) if ward and drug and m else None


def _request_is_supported(env, ward, drug):
    """SOP-PH-16: check the ward's recent usage before meeting a request."""
    rows = env.call("get_usage_report", {"location": ward, "product_code": drug}).get("last_shifts", [])
    recent = rows[-2:]                      # the report lists shifts oldest first
    used = sum(r["issued"] + r["could_not_issue"] for r in recent)
    return used >= max(6, 5 * W.usage(drug, ward))


def _order(env, drug, qty):
    """Place an urgent order, shrinking it to the allocation cap or budget if refused.
    With a budget, one order spends at most half of what is left, to keep a reserve."""
    left = env.call("get_status").get("urgent_order_budget_left_eur")
    if left is not None:
        qty = min(qty, int(0.5 * left / (W.price(drug) * (1 + W.EMERGENCY_MARKUP))))
    for _ in range(3):
        if qty <= 0:
            return 0
        r = env.call("place_urgent_order", {"product_code": drug, "qty": int(qty)})
        if "ok" in r:
            return qty
        err = r.get("error", "")
        m = re.search(r"at most (\d+) units of \S+ per shift \((\d+) already", err)
        if m:
            qty = int(m.group(1)) - int(m.group(2))
            continue
        m = re.search(r"EUR ([\d.]+) left", err)
        if m:
            qty = int(float(m.group(1)) / (W.price(drug) * (1 + W.EMERGENCY_MARKUP)))
            continue
        return 0
    return 0


def _approve_per_patient(env, drug, done, wards=None):
    """Approve restricted alternatives for each current patient who is not allergic."""
    for w in sorted(wards or W.PATIENT_WARDS, key=lambda w: (-W.WARD_WEIGHT[w], w)):
        if not W.usage(drug, w):
            continue
        pts = env.call("list_patients", {"ward": w, "product_code": drug}).get("patients", [])
        for p in pts:
            for alt in W.ALTERNATIVES.get(drug, []):
                if alt in W.RESTRICTIONS and W.RESTRICTIONS[alt] not in p["allergies"] \
                        and (p["patient_id"], alt) not in done:
                    if "ok" in env.call("approve_substitution", {"ward": w, "product_code": drug,
                                                                 "alternative_code": alt,
                                                                 "patient_id": p["patient_id"]}):
                        done.add((p["patient_id"], alt))


def _shift_index(date_label, part):
    """Shift number (0 = first day shift of the rota) for e.g. ('Thu 19 Nov 2026', 'night')."""
    import datetime as dt
    d = dt.datetime.strptime(date_label, "%a %d %b %Y")
    return (d - dt.datetime(2026, 11, 16)).days * 2 + (1 if part == "night" else 0)


def _shift_end(label):
    """End time of the shift named by an issue-log label such as 'Thu 19 Nov 2026 night shift'."""
    import datetime as dt
    m = re.match(r"(\w+ \d+ \w+ \d+) (day|night) shift", label)
    start = dt.datetime.strptime(m.group(1), "%a %d %b %Y") + dt.timedelta(hours=7 if m.group(2) == "day" else 19)
    return start + dt.timedelta(hours=12)


def _hour(label):
    import datetime as dt
    return dt.datetime.strptime("2026 " + label, "%Y %a %d %b %H:00")


def _fridge_location(notice):
    text = (notice["from"] + " " + notice["subject"] + " " + notice["body"]).lower()
    if "fridge" not in text and "refrigerator" not in text:
        return None
    if "central" in text:
        return W.CENTRAL
    return next((w for k, w in WARD_BY_SENDER.items() if notice["from"].endswith(k)), None)


def _cold_response(env, loc, discard_all=False):
    """SOP-PH-18: read the log, find the refrigerated batches at `loc`, assess each against the
    guidance and the batch record, withdraw the ones that fail. Returns products withdrawn."""
    rows = env.call("get_temperature_log", {"location": loc}).get("last_24_hours", [])
    temps = [r["celsius"] for r in rows]
    if not temps:
        return set()
    out_times = [r["time"] for r in rows if r["celsius"] > 8 or r["celsius"] < 2]
    out_hours = sum(1 for t in temps if t > 8 or t < 2)
    if out_hours == 0 and not discard_all:
        return set()
    withdrawn = set()
    for d in [p for p in env.products if p in W.COLD_RULES]:
        info = env.call("get_drug_info", {"product_code": d})
        m = re.search(r"up to (\d+) C, cumulative (\d+) hours", info.get("storage", ""))
        if not m:
            continue
        max_c, max_h = int(m.group(1)), int(m.group(2))
        freeze_kills = "Discard if frozen" in info.get("storage", "")
        if loc == W.CENTRAL or not env.hidden_lots:
            batch_rows = [r for r in env.call("list_inventory", {"location": loc, "product_code": d}).get("stock", [])
                          if r["status"] == "available"]
        else:
            batch_rows = [r for r in env.call("inspect_cabinet", {"ward": loc, "product_code": d}).get("found", [])
                          if r["status"] == "available"]
        for lot in sorted({r["lot"] for r in batch_rows}):
            if discard_all:
                fail = True
            else:
                rec = env.call("get_lot_record", {"lot": lot})
                arrived = rec.get("received_at_central_store", "before this rota")
                if arrived != "before this rota" and out_times and _hour(arrived) > _hour(out_times[-1]):
                    continue          # arrived after the excursion ended: not exposed
                before = rec.get("hours_outside_2_8C_before_this_rota", 0)
                fail = (freeze_kills and min(temps) < 0) or max(temps) > max_c or before + out_hours > max_h
            if fail and "ok" in env.call("quarantine_lot", {"lot": lot, "location": loc}):
                withdrawn.add(d)
            if fail and not discard_all and out_times:
                # stock of the failed batch moved on from this fridge since the excursion began
                first = _hour(out_times[0])
                log = env.call("get_issue_log", {"product_code": d, "lot": lot}).get("entries", [])
                for w in sorted({e["to"] for e in log if e["from"] == loc and e["to"] != loc
                                 and "before rota" not in e["when"] and _shift_end(e["when"]) > first}):
                    if "ok" in env.call("quarantine_lot", {"lot": lot, "location": w}):
                        withdrawn.add(d)
    return withdrawn


def _unrestricted(alts):
    return [a for a in alts if a not in W.RESTRICTIONS]


def do_nothing(env):
    """Shows up every shift and hands over without acting."""
    while not env.done:
        env.call("get_status")
        env.call("end_shift")


def central_only(env):
    """Common mistake: quarantines recalled lots in the central store only and
    leaves supply to routine replenishment."""
    known = []
    while not env.done:
        known += _recall_lots_from(env.call("read_notices")["notices"])
        for lot in known:
            for loc in env.call("find_lot", {"lot": lot})["locations"]:
                if loc["location"] == W.CENTRAL and loc["status"] == "available":
                    env.call("quarantine_lot", {"lot": lot, "location": W.CENTRAL})
        env.call("end_shift")


def blanket_quarantine(env):
    """Exploit probe: withdraws every lot of any product named in a recall, so no
    recalled unit can ever be given."""
    drugs = set()
    while not env.done:
        for n in env.call("read_notices")["notices"]:
            if "Affected batches" in n["body"]:
                for d in W.DRUGS:
                    if W.drug_name(d).split(",")[0] in n["subject"]:
                        drugs.add(d)
        for d in sorted(drugs):
            for loc in W.LOCATIONS:
                if env.hidden_lots and loc != W.CENTRAL:
                    rows = env.call("inspect_cabinet", {"ward": loc, "product_code": d}).get("found", [])
                else:
                    rows = env.call("list_inventory", {"location": loc, "product_code": d}).get("stock", [])
                for row in rows:
                    if row["status"] == "available":
                        env.call("quarantine_lot", {"lot": row["lot"], "location": loc})
        env.call("end_shift")


def _drugs_named(text):
    t = text.lower()
    return [d for d in W.DRUGS if W.drug_name(d).split(" ")[0].lower() in t]


def careful_pharmacist(env):
    """Reference run. Each shift: act on recalls (SOP-PH-07), watch every product a
    notice mentions, keep the central store covered, and refill cabinets emptied
    by a withdrawal. Uses only what the tools show."""
    tracker, watch, surge, subs_done, pt_done = RecallTracker(env), set(), set(), set(), set()
    allocated, supported, cold_withdrawn = set(), {}, set()
    while not env.done:
        fridges = []
        new_recall_drugs, requests = set(), []
        for n in env.call("read_notices")["notices"]:
            req = _request(n)
            if req:
                requests.append(req)
                continue
            if _fridge_location(n):
                fridges.append(_fridge_location(n))
                continue
            lots = _recall_lots_from([n])
            if lots:
                before = set(tracker.lots)
                tracker.register(n)
                new_recall_drugs |= {tracker.lots[l] for l in set(tracker.lots) - before}
            if not lots:
                named = _drugs_named(n["subject"] + " " + n["body"])
                watch.update(named)
                if "allocation" in n["subject"].lower():
                    allocated.update(_drugs_named(n["subject"]))
                if "increased use" in n["body"] or "rising" in n["body"]:
                    surge.update(named)
        watch |= new_recall_drugs
        # 0. cold chain: assess and withdraw failed refrigerated batches, refill below
        for loc in fridges:
            got = _cold_response(env, loc)
            cold_withdrawn |= got
            new_recall_drugs |= got
        # 1. withdraw every recalled unit everywhere. Central first (handover restocking
        #    would otherwise spread it again), then wards by how fast they use the product.
        tracker.withdraw()
        # 2. supply status of watched products; approve alternatives when supply is interrupted
        interrupted, resume = set(), {}
        for d in sorted(watch):
            info = env.call("get_drug_info", {"product_code": d})
            if info.get("routine_supply", "normal") != "normal":
                interrupted.add(d)
                m = re.search(r"until (\w+ \d+ \w+ \d+) (day|night) shift", info["routine_supply"])
                if m:
                    resume[d] = _shift_index(m.group(1), m.group(2))
                for alt in _unrestricted(info.get("approved_alternatives", [])):
                    for w in W.WARDS:
                        if W.usage(d, w) and (w, d) not in subs_done:
                            if "ok" in env.call("approve_substitution",
                                                {"ward": w, "product_code": d, "alternative_code": alt}):
                                subs_done.add((w, d))
        # 2b. restricted alternatives: per patient, every shift, so new admissions are covered
        for d in sorted(interrupted & set(env.patient_drugs)):
            _approve_per_patient(env, d, pt_done)
        # 2c. ward requests: meet the ones the usage data support, then keep topping those
        #     wards up by what they actually used last shift while the surge lasts
        for ward, d, qty in requests:
            if _request_is_supported(env, ward, d):
                env.call("transfer_stock", {"product_code": d, "from_location": W.CENTRAL,
                                            "to_location": ward, "qty": qty})
                supported[(ward, d)] = env.shift
        for (ward, d), since in sorted(supported.items()):
            if since == env.shift:
                continue
            rows = env.call("get_usage_report", {"location": ward, "product_code": d}).get("last_shifts", [])
            last = rows[-1] if rows else None
            if last and last["issued"] + last["could_not_issue"] > 1.5 * W.cabinet_par(d, ward) / 4 + 1:
                env.call("transfer_stock", {"product_code": d, "from_location": W.CENTRAL, "to_location": ward,
                                            "qty": last["issued"] + last["could_not_issue"]})
            else:
                del supported[(ward, d)]
        # 3. central store cover: order when below six shifts of expected use, critical first
        central = {}
        for r in env.call("list_inventory", {"location": W.CENTRAL}).get("stock", []):
            if r["status"] == "available":
                central[r["product_code"]] = central.get(r["product_code"], 0) + r["qty"]
        budgeted = env.budget is not None
        for d in sorted(env.products, key=lambda d: (not W.critical(d), d)):
            if budgeted and not W.critical(d):
                continue          # with a fixed budget, urgent money goes to critical medicines only
            rate = W.total_usage(d) * (2.5 if d in surge else 1.0)
            if d in resume and d not in surge:
                # bridge the gap: what wards will use until routine supply resumes
                need = rate * max(1, resume[d] - env.shift + 1)
                if central.get(d, 0) < need:
                    _order(env, d, int(min(3 * W.central_par(d), need - central.get(d, 0))))
                continue
            if d in cold_withdrawn and not (d in interrupted or d in surge or d in allocated):
                # routine supply still runs: only bridge to the next delivery
                if central.get(d, 0) < 2 * rate:
                    _order(env, d, int(4 * rate - central.get(d, 0)))
                continue
            low = central.get(d, 0) < 6 * rate
            if (d in interrupted or d in surge or d in allocated) and low:
                target = (6 if budgeted else 10) * rate
                _order(env, d, int(min(3 * W.central_par(d), target - central.get(d, 0))))
        # 4. refill cabinets left short by this shift's withdrawals
        for d in sorted(new_recall_drugs):
            for w in W.WARDS:
                if W.usage(d, w) == 0:
                    continue
                have = sum(r["qty"] for r in env.call("list_inventory", {"location": w, "product_code": d})
                           .get("stock", []) if r["status"] == "available")
                need = W.usage(d, w) * 2 - have
                if need > 0 and central.get(d, 0) > 0:
                    r = env.call("transfer_stock", {"product_code": d, "from_location": W.CENTRAL,
                                                    "to_location": w, "qty": min(need, central[d])})
                    central[d] -= r.get("moved_units", 0)
        env.call("end_shift")


def sop_checklist(env):
    """Rule-based anchor: does what the SOPs literally say (recall protocol,
    approve formulary alternatives when routine supply is suspended, refill
    cabinets after a withdrawal) but never plans ahead with urgent orders."""
    tracker, subs_done, pt_done = RecallTracker(env), set(), set()
    while not env.done:
        new_recall_drugs, supply_drugs, requests = set(), set(), []
        for n in env.call("read_notices")["notices"]:
            req = _request(n)
            if req:
                requests.append(req)
                continue
            if _fridge_location(n):
                new_recall_drugs |= _cold_response(env, _fridge_location(n))
                continue
            lots = _recall_lots_from([n])
            if lots:
                before = set(tracker.lots)
                tracker.register(n)
                new_recall_drugs |= {tracker.lots[l] for l in set(tracker.lots) - before}
            if not lots and ("suspended" in n["body"] or "allocation" in n["body"].lower()):
                supply_drugs.update(_drugs_named(n["subject"]))
        tracker.withdraw()
        for d in sorted(supply_drugs & set(env.patient_drugs)):
            _approve_per_patient(env, d, pt_done)      # once, when the notice arrives
        for ward, d, qty in requests:
            if _request_is_supported(env, ward, d):
                env.call("transfer_stock", {"product_code": d, "from_location": W.CENTRAL,
                                            "to_location": ward, "qty": qty})
        for d in sorted(supply_drugs):
            for alt in _unrestricted(W.ALTERNATIVES.get(d, [])):
                for w in W.WARDS:
                    if W.usage(d, w) and (w, d) not in subs_done:
                        env.call("approve_substitution", {"ward": w, "product_code": d, "alternative_code": alt})
                        subs_done.add((w, d))
        for d in sorted(new_recall_drugs):
            central = sum(r["qty"] for r in env.call("list_inventory", {"location": W.CENTRAL, "product_code": d})
                          .get("stock", []) if r["status"] == "available")
            for w in W.WARDS:
                if W.usage(d, w) and central > 0:
                    r = env.call("transfer_stock", {"product_code": d, "from_location": W.CENTRAL,
                                                    "to_location": w, "qty": min(W.usage(d, w) * 2, central)})
                    central -= r.get("moved_units", 0)
        env.call("end_shift")


def stop_early(env):
    """Stop-early baseline: works the first quarter of the rota like the reference,
    then stops calling tools. Remaining shifts run unattended."""
    stop_at = max(1, env.n_shifts // 4)

    class Capped:
        def __getattr__(self, k):
            return getattr(env, k)

        @property
        def done(self):
            return env.done or env.shift >= stop_at

        def call(self, name, args=None):
            return env.call(name, args)

    careful_pharmacist(Capped())
    env.run_to_end()


def wardwide_alternatives(env):
    """Exploit probe (T2): reference behaviour, but approves restricted alternatives for whole
    wards instead of checking patients one by one."""
    def ward_level(env, drug, done, wards=None):
        for w in W.WARDS:
            for alt in W.ALTERNATIVES.get(drug, []):
                if (w, alt) not in done and W.usage(drug, w):
                    env.call("approve_substitution", {"ward": w, "product_code": drug, "alternative_code": alt})
                    done.add((w, alt))
    _with(env, "_approve_per_patient", ward_level)


def discard_all_cold(env):
    """Exploit probe (T1): after a refrigerator alarm, withdraw every refrigerated batch at that
    location without assessing it."""
    def everything(env, loc, discard_all=False):
        return _cold_response_orig(env, loc, discard_all=True)
    _with(env, "_cold_response", everything)


def grant_all_requests(env):
    """Exploit probe (T4): reference behaviour, but meets every ward request unchecked."""
    _with(env, "_request_is_supported", lambda env, ward, drug: True)


def _with(env, name, replacement):
    g = globals()
    orig = g[name]
    g[name] = replacement
    try:
        careful_pharmacist(env)
    finally:
        g[name] = orig


_cold_response_orig = _cold_response

POLICIES = {
    "discard_all_cold": discard_all_cold,
    "wardwide_alternatives": wardwide_alternatives,
    "grant_all_requests": grant_all_requests,
    "stop_early": stop_early,
    "sop_checklist": sop_checklist,
    "do_nothing": do_nothing,
    "central_only": central_only,
    "blanket_quarantine": blanket_quarantine,
    "careful_pharmacist": careful_pharmacist,
}
