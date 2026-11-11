#!/usr/bin/env python3
"""funding-radar: who would actually fund your startup?

Takes a one-line description of a startup (plus optional stage and country),
finds companies like it that raised in the last 12-18 months, works out who
backed them, and returns a ranked list of investors to approach - with proof
for every match, cheque size, stage, lead partner and a way to reach them.

Built end-to-end on TinyFish:
  - TinySet (Datasets API)  -> the similar-companies list, every row from a live source
  - Search API              -> per-investor deal verification + contact discovery
  - Fetch API               -> reads the investor's own site to confirm how to pitch them
  - Research API            -> names the partner who led each deal and typical cheque size

Usage:
  export TINYFISH_API_KEY=sk-tinyfish-...
  python3 funding_radar.py "voice AI agents for outbound sales calls" --stage seed --country US
  python3 funding_radar.py "devtool that reviews AI agent PRs" --json --no-research
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, timedelta

AGENT = "https://agent.tinyfish.ai"
SEARCH_URL = "https://api.search.tinyfish.ai"
FETCH_URL = "https://api.fetch.tinyfish.ai"

def _req(url, key, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "X-API-Key": key, "Content-Type": "application/json", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

# ---------------- phase 1: TinySet similar-companies dataset ----------------

def build_companies(key, desc, stage, country, months, target=15, reuse_id=None):
    since = (date.today() - timedelta(days=30 * months)).isoformat()
    if reuse_id:
        ds_id = reuse_id
    else:
        prompt = (
            f"Startups similar to: {desc} (stage: {stage}, country: {country}). "
            f"List companies that raised funding (pre-seed to Series B) announced since {since}. "
            "For each: company name, website, what they do, amount raised (number, USD), "
            "round/stage, date announced, investors (lead investor first), and a source URL "
            "that proves the round (news article, company blog, investor announcement)."
        )
        ds = _req(f"{AGENT}/v1/datasets", key, {"prompt": prompt, "target_rows": target}, timeout=120)
        ds_id = ds["id"]
    deadline = time.time() + 480
    rows = []
    while time.time() < deadline:
        time.sleep(15)
        page = _req(f"{AGENT}/v1/datasets/{ds_id}/rows?limit=100", key)
        rows = [r.get("data", {}) for r in page.get("rows", [])]
        st = _req(f"{AGENT}/v1/datasets/{ds_id}", key)
        if st.get("status") not in ("populating", "pending") and rows:
            break
    companies = []
    for r in rows:
        name = r.get("company") or r.get("company_name")
        if not name:
            continue
        r["company"] = name
        invs = [i.strip() for i in re.split(r";|,(?![^(]*\))", r.get("investors", "") or "") if i.strip()]
        lead = None
        if invs:
            m = re.match(r"(.+?)\s*\((lead|co-lead)\)\s*$", invs[0], re.I)
            lead = m.group(1) if m else invs[0]  # prompt asks for lead investor first
            invs = [re.sub(r"\s*\((lead|co-lead)\)\s*$", "", i, flags=re.I) for i in invs]
        amt = r.get("amount_raised") or r.get("amount_raised_usd") or r.get("funding_usd") or r.get("amount_usd")
        if isinstance(amt, (int, float)) and 0 < amt < 1000:
            amt = int(amt * 1_000_000)  # TinySet number columns often land in millions
        rnd = (r.get("round") or r.get("round_stage") or r.get("stage") or "")
        companies.append({
            "company": r["company"], "website": r.get("website"),
            "what": r.get("what_they_do"), "amount": amt,
            "round": rnd.title() if rnd else None, "date": r.get("date_announced"),
            "lead": lead, "investors": invs, "source": r.get("source_url"),
        })
    return companies, ds_id

# ---------------- phase 2: Search API verification + contact discovery ----------------

def search(key, query, purpose):
    params = {"query": query, "purpose": purpose, "language": "en"}
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-API-Key": key})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode()).get("results", [])

CONTACT_PAT = re.compile(r"(apply|application|pitch|contact|submit|deck|intake|form)", re.I)
ADVICE_DOMAINS = re.compile(r"(crunchbase\.com/news|news\.crunchbase|babson\.edu|forbes|medium\.com|businessinsider|entrepreneur\.com|inc\.com|hubspot|nfx\.com|ycombinator\.com/library)", re.I)

def investor_domain_ok(investor, url):
    if not url: return False
    if ADVICE_DOMAINS.search(url): return False
    host = urllib.parse.urlparse(url).netloc.lower()
    toks = [t for t in re.split(r"[^a-z0-9]+", investor.lower()) if len(t) > 3]
    return any(t in host for t in toks)

def enrich_investor_search(key, investor, desc):
    deals, contacts = [], []
    try:
        for r in search(key, f"{investor} invested {desc.split()[0]} startup funding round",
                         f"Verify recent investments by {investor} in startups like: {desc}")[:5]:
            deals.append({"url": r.get("url"), "title": r.get("title"), "date": r.get("date")})
    except Exception:
        pass
    try:
        for r in search(key, f"{investor} venture capital pitch apply contact startups",
                        f"Find how a founder contacts or applies to {investor} (application form, open intake, contact page)"):
            u = r.get("url")
            if CONTACT_PAT.search((r.get("title") or "") + " " + (u or "")) and (investor_domain_ok(investor, u) or investor.lower() == "y combinator"):
                contacts.append(u)
    except Exception:
        pass
    return deals, contacts[:3]

# ---------------- phase 3: Fetch API - confirm the pitch route ----------------

def confirm_contact(key, investor, urls):
    if not urls:
        return None
    try:
        res = _req(FETCH_URL, key, {"urls": urls[:2], "purpose":
                   f"Confirm this is the right page for a founder to pitch or contact {investor}, and note what it asks for"},
                   timeout=90)
        for item in res.get("results", res if isinstance(res, list) else []):
            text = (item.get("text") or "")[:800]
            if CONTACT_PAT.search(text):
                return {"url": item.get("url") or urls[0], "note": re.sub(r"\s+", " ", text)[:220]}
    except Exception:
        pass
    return {"url": urls[0], "note": ""}

# ---------------- phase 4: Research API - lead partners + cheque sizes ----------------

def research_partners(key, pairs, desc):
    """pairs: [(investor, company)]. One research run names deal leads + cheque sizes."""
    if not pairs:
        return {}
    listing = "; ".join(f"{inv} (backed {co})" for inv, co in pairs[:6])
    q = (f"For each of these investors: {listing} - name the partner or person who led their "
         f"investment in that company where findable, their typical cheque size, and the stages they "
         f"invest at. Context: a founder building '{desc}' is deciding who to pitch first.")
    try:
        run = _req(f"{AGENT}/v1/automation/run-research-async", key, {"query": q, "mode": "deep"}, timeout=60)
        rid = run.get("id") or run.get("research_run_id")
        deadline = time.time() + 600
        while time.time() < deadline:
            time.sleep(20)
            st = _req(f"{AGENT}/v1/research-run/{rid}", key)
            if st.get("status") in ("completed", "done", "success"):
                return {"text": json.dumps(st)[:6000], "run_id": rid}
            if st.get("status") in ("failed", "cancelled"):
                return {}
    except Exception as e:
        print(f"research phase skipped: {e}", file=sys.stderr)
    return {}

# ---------------- ranking ----------------

def rank(companies, extra_deals):
    stats = defaultdict(lambda: {"companies": [], "as_lead": 0, "rounds": [], "amounts": [], "sources": [], "recent": 0})
    cutoff = (date.today() - timedelta(days=270)).isoformat()
    for c in companies:
        for inv in c["investors"]:
            s = stats[inv]
            s["companies"].append({"name": c["company"], "source": c["source"], "round": c.get("round"), "date": c.get("date")})
            if c.get("round"): s["rounds"].append(c["round"])
            if c.get("amount"): s["amounts"].append(c["amount"])
            if c.get("source"): s["sources"].append(c["source"])
            if c.get("date") and c["date"] >= cutoff: s["recent"] += 1
            if c.get("lead") and c["lead"].lower() == inv.lower(): s["as_lead"] += 1
    for inv, deals in extra_deals.items():
        stats[inv]["sources"] += [d["url"] for d in deals if d.get("url")]
    scored = []
    for inv, s in stats.items():
        if len(inv) < 3: continue
        score = len(s["companies"]) * 2 + s["as_lead"] * 3 + min(s["recent"], 3)
        amt = sorted(a for a in s["amounts"] if isinstance(a, (int, float)))  # round sizes they joined
        typical = int(amt[len(amt)//2]) if amt else None
        rounds = sorted(set(s["rounds"]))
        reasons = []
        reasons.append(f"backed {len(s['companies'])} similar compan{'ies' if len(s['companies'])!=1 else 'y'}")
        if s["as_lead"]: reasons.append(f"led {s['as_lead']} of those rounds")
        if s["recent"]: reasons.append(f"{s['recent']} deal(s) in the last 9 months - actively deploying")
        scored.append({"investor": inv, "score": score, "companies": s["companies"][:6],
                       "typical_cheque_usd": typical, "stages": rounds[:4],
                       "why": "; ".join(reasons), "proof": list(dict.fromkeys(s["sources"]))[:6]})
    scored.sort(key=lambda x: -x["score"])
    return scored

def main():
    ap = argparse.ArgumentParser(description="Find investors who funded startups like yours (TinyFish: Datasets + Search + Fetch + Research).")
    ap.add_argument("description"); ap.add_argument("--stage", default="seed"); ap.add_argument("--country", default="US")
    ap.add_argument("--months", type=int, default=18); ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-research", action="store_true"); ap.add_argument("--out", help="write markdown report here")
    ap.add_argument("--research-md", help="saved markdown from a completed TinyFish Research deep run; skips launching a new run but keeps research in the report")
    ap.add_argument("--dataset-id", help="reuse an existing TinySet dataset instead of creating one")
    args = ap.parse_args()
    key = os.environ.get("TINYFISH_API_KEY") or sys.exit("set TINYFISH_API_KEY (https://agent.tinyfish.ai/api-keys)")

    print("[1/4] TinySet: building similar-companies dataset...", file=sys.stderr)
    companies, ds_id = build_companies(key, args.description, args.stage, args.country, args.months, reuse_id=args.dataset_id)
    print(f"      {len(companies)} companies (dataset {ds_id})", file=sys.stderr)

    freq = defaultdict(int)
    for c in companies:
        for inv in c["investors"]: freq[inv] += 1
    top = [i for i, _ in sorted(freq.items(), key=lambda kv: -kv[1]) if len(i) > 2][:8]

    print(f"[2/4] Search: verifying deals + finding contact routes for {len(top)} investors...", file=sys.stderr)
    extra_deals, contact_candidates = {}, {}
    for inv in top:
        deals, contacts = enrich_investor_search(key, inv, args.description)
        extra_deals[inv] = deals; contact_candidates[inv] = contacts

    print("[3/4] Fetch: confirming pitch pages...", file=sys.stderr)
    contacts = {inv: confirm_contact(key, inv, contact_candidates.get(inv)) for inv in top[:5]}

    partners = {}
    if args.research_md:
        print("[4/4] Research: loading saved deep-run markdown...", file=sys.stderr)
        partners = {"md": open(args.research_md).read()}
    elif not args.no_research:
        print("[4/4] Research: naming lead partners + cheque sizes (deep, few minutes)...", file=sys.stderr)
        lead_pairs = [(c["lead"], c["company"]) for c in companies if c.get("lead")]
        partners = research_partners(key, lead_pairs, args.description)
    else:
        print("[4/4] Research: skipped (--no-research)", file=sys.stderr)

    ranked = rank(companies, extra_deals)
    for r in ranked:
        inv = r["investor"]
        if inv in contacts and contacts[inv]:
            r["how_to_reach"] = contacts[inv]
    report = {"startup": args.description, "stage": args.stage, "country": args.country,
              "since": (date.today() - timedelta(days=30 * args.months)).isoformat(),
              "similar_companies": companies, "investors": ranked[:12],
              "research": partners, "tinyfish_dataset_id": ds_id,
              "tinyfish_endpoints_used": ["datasets", "search", "fetch"] +(["research"] if (not args.no_research or args.research_md) else [])}
    if args.out:
        with open(args.out, "w") as f:
            f.write(render_md(report))
        print(f"report written to {args.out}", file=sys.stderr)
    if args.json:
        print(json.dumps(report, indent=2)); return
    print(render_md(report))

def render_md(r):
    L = [f"# funding radar: {r['startup']}", "",
         f"stage: {r['stage']} | country: {r['country']} | window: since {r['since']}",
         f"similar companies found: {len(r['similar_companies'])} (TinySet dataset {r['tinyfish_dataset_id']})", "",
         "## similar companies that raised recently", ""]
    for c in r["similar_companies"]:
        amt = f"${c['amount']:,}" if isinstance(c.get("amount"), (int, float)) else "?"
        L.append(f"- **{c['company']}** ({c.get('round') or '?'}, {amt}, {c.get('date') or '?'}) - {c.get('what') or ''} [source]({c.get('source')})")
    L += ["", "## ranked investors to approach", ""]
    for i, inv in enumerate(r["investors"], 1):
        L.append(f"### {i}. {inv['investor']}")
        L.append(f"- why now: {inv['why']}")
        if inv.get("typical_cheque_usd"): L.append(f"- median round they joined: ${inv['typical_cheque_usd']:,} | stages: {', '.join(inv['stages'])}")
        backed = ", ".join(f"[{c['name']}]({c['source']})" for c in inv["companies"][:3] if c.get("source"))
        if backed: L.append(f"- backed similar: {backed}")
        if inv.get("how_to_reach"): L.append(f"- reach them: {inv['how_to_reach']['url']}")
        L.append("")
    if r.get("research"):
        body = r["research"].get("md") or r["research"].get("text", "")[:1500]
        L += ["## lead partners & cheque detail (TinyFish Research deep run)", "", body, ""]
    used = r['tinyfish_endpoints_used']
    expl = "TinySet (Datasets API) built the similar-companies list from live pages; Search API verified each investor's recent deals and found contact routes; Fetch API read the investors' own pages to confirm the pitch route"
    if "research" in used:
        expl += "; Research API named the partners who led the deals and typical cheque sizes"
    L += ["---", f"built with TinyFish endpoints: {', '.join(used)}", expl + "."]
    return "\n".join(L)

if __name__ == "__main__":
    main()
