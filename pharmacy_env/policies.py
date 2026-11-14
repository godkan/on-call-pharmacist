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
    tracker, watch, surge, subs_done = RecallTracker(env), set(), set(), set()
    while not env.done:
        new_recall_drugs = set()
        for n in env.call("read_notices")["notices"]:
            lots = _recall_lots_from([n])
            if lots:
                before = set(tracker.lots)
                tracker.register(n)
                new_recall_drugs |= {tracker.lots[l] for l in set(tracker.lots) - before}
            if not lots:
                named = _drugs_named(n["subject"] + " " + n["body"])
                watch.update(named)
                if "increased use" in n["body"] or "rising" in n["body"]:
                    surge.update(named)
        watch |= new_recall_drugs
        # 1. withdraw every recalled unit everywhere. Central first (handover restocking
        #    would otherwise spread it again), then wards by how fast they use the product.
        tracker.withdraw()
        # 2. supply status of watched products; approve alternatives when supply is interrupted
        interrupted = set()
        for d in sorted(watch):
            info = env.call("get_drug_info", {"product_code": d})
            if info.get("routine_supply", "normal") != "normal":
                interrupted.add(d)
                for alt in _unrestricted(info.get("approved_alternatives", [])):
                    for w in W.WARDS:
                        if W.usage(d, w) and (w, d) not in subs_done:
                            if "ok" in env.call("approve_substitution",
                                                {"ward": w, "product_code": d, "alternative_code": alt}):
                                subs_done.add((w, d))
        # 3. central store cover: order when below six shifts of expected use
        central = {}
        for r in env.call("list_inventory", {"location": W.CENTRAL}).get("stock", []):
            if r["status"] == "available":
                central[r["product_code"]] = central.get(r["product_code"], 0) + r["qty"]
        for d in W.DRUGS:
            rate = W.total_usage(d) * (2.5 if d in surge else 1.0)
            if (d in interrupted or d in surge) and central.get(d, 0) < 6 * rate:
                env.call("place_urgent_order", {"product_code": d,
                                                "qty": int(min(3 * W.central_par(d), 10 * rate - central.get(d, 0)))})
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
    tracker, subs_done = RecallTracker(env), set()
    while not env.done:
        new_recall_drugs, supply_drugs = set(), set()
        for n in env.call("read_notices")["notices"]:
            lots = _recall_lots_from([n])
            if lots:
                before = set(tracker.lots)
                tracker.register(n)
                new_recall_drugs |= {tracker.lots[l] for l in set(tracker.lots) - before}
            if not lots and ("suspended" in n["body"] or "allocation" in n["body"].lower()):
                supply_drugs.update(_drugs_named(n["subject"]))
        tracker.withdraw()
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


POLICIES = {
    "stop_early": stop_early,
    "sop_checklist": sop_checklist,
    "do_nothing": do_nothing,
    "central_only": central_only,
    "blanket_quarantine": blanket_quarantine,
    "careful_pharmacist": careful_pharmacist,
}
