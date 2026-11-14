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
                for row in env.call("list_inventory", {"location": loc, "product_code": d}).get("stock", []):
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
    known_lots, watch, surge, subs_done = [], set(), set(), set()
    while not env.done:
        new_recall_drugs = set()
        for n in env.call("read_notices")["notices"]:
            lots = _recall_lots_from([n])
            for lot in lots:
                locs = env.call("find_lot", {"lot": lot})["locations"]
                if locs:
                    known_lots.append(lot)
                    new_recall_drugs.add(locs[0]["product_code"])
            if not lots:
                named = _drugs_named(n["subject"] + " " + n["body"])
                watch.update(named)
                if "increased use" in n["body"] or "rising" in n["body"]:
                    surge.update(named)
        watch |= new_recall_drugs
        # 1. withdraw every recalled unit everywhere. Central first (handover restocking
        #    would otherwise spread it again), then wards by how fast they use the product.
        hits = []
        for lot in known_lots:
            for loc in env.call("find_lot", {"lot": lot})["locations"]:
                if loc["status"] == "available":
                    rank = -1e9 if loc["location"] == W.CENTRAL else -W.usage(loc["product_code"], loc["location"])
                    hits.append((rank, loc["location"], lot))
        for _, where, lot in sorted(hits):
            env.call("quarantine_lot", {"lot": lot, "location": where})
        # 2. supply status of watched products; approve alternatives when supply is interrupted
        interrupted = set()
        for d in sorted(watch):
            info = env.call("get_drug_info", {"product_code": d})
            if info.get("routine_supply", "normal") != "normal":
                interrupted.add(d)
                for alt in info.get("approved_alternatives", []):
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
    known_lots, subs_done = [], set()
    while not env.done:
        new_recall_drugs, supply_drugs = set(), set()
        for n in env.call("read_notices")["notices"]:
            lots = _recall_lots_from([n])
            for lot in lots:
                locs = env.call("find_lot", {"lot": lot})["locations"]
                if locs:
                    known_lots.append(lot)
                    new_recall_drugs.add(locs[0]["product_code"])
            if not lots and ("suspended" in n["body"] or "allocation" in n["body"].lower()):
                supply_drugs.update(_drugs_named(n["subject"]))
        for lot in known_lots:
            for loc in env.call("find_lot", {"lot": lot})["locations"]:
                if loc["status"] == "available":
                    env.call("quarantine_lot", {"lot": lot, "location": loc["location"]})
        for d in sorted(supply_drugs):
            for alt in W.ALTERNATIVES.get(d, []):
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
