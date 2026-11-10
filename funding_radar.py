#!/usr/bin/env python3
"""funding-radar: who would actually fund your startup?

Takes a one-line description of a startup, finds companies like it that
raised in the last 12-18 months, works out who backed them, and returns a
ranked list of investors to approach, with proof for every match.

Built on the TinyFish Search API (https://docs.tinyfish.ai/search-api).
No dependencies beyond the Python standard library.

Usage:
  export TINYFISH_API_KEY=sk-tinyfish-...
  python3 funding_radar.py "voice AI agents for outbound sales calls"
  python3 funding_radar.py --json "devtool for reviewing AI agent PRs"
"""
import argparse, json, os, re, sys, urllib.parse, urllib.request
from collections import defaultdict
from datetime import date, timedelta

SEARCH_URL = "https://api.search.tinyfish.ai"
STOP = set("""a an and are as at be by for from has have in into is it its of on or that the their this to with your our we you ai powered based platform tool tools app apps startup company companies build building helps help users using software solution solutions""".split())

INVESTOR_PATTERNS = [
    re.compile(r'(?:led by|lead by|from|backed by|investors?(?:\s+including)?|participation from|with participation from|joined by|alongside)\s+([^.,;()]+)', re.I),
]
AMOUNT_RE = re.compile(r'(?:raised|raises|lands|closes|secured|gets|snagged|bags)\s+(?:a\s+)?\$?([\d,.]+\s*(?:million|billion|m|bn|M|B))', re.I)
COMPANY_RE = re.compile(r'^([A-Z][\w.+-]*(?:\s[A-Z][\w.+-]+)?)\s*[:,]?\s*(?:has\s+)?(?:raised|raises|lands|closes|secured|gets|snagged|bags|\$)')
BAD_INVESTORS = set("""the a an and or of in on at to for with by from seed series funding round capital ventures partners""".split())
GENERIC = re.compile(r'^(?:the|a|an|seed|series|funding|round|new|existing|several|other|unnamed|undisclosed)', re.I)

def keywords(desc):
    words = [w.lower().strip(".,;:!?()\"'") for w in desc.split()]
    return [w for w in words if len(w) > 2 and w not in STOP][:8]

def search(api_key, query, purpose, after):
    params = {"query": query, "purpose": purpose, "after_date": after, "language": "en"}
    url = SEARCH_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"X-API-Key": api_key})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())

NAMEY = re.compile(r"^[A-Z][\w.&+-]*(?:\s+(?:[A-Z][\w.&+-]*|de|van|and))*$")
BANNED_WORDS = re.compile(r'\b(?:navigating|insurers|customers|users|companies|startup|founder|raised|funding|round|announced|today|here)\b', re.I)

def split_investors(chunk):
    parts = re.split(r',| and |;|&', chunk)
    out = []
    for p in parts:
        p = p.strip().strip('.').strip()
        p = re.sub(r'^(?:also|as well as|both|including)\s+', '', p, flags=re.I)
        p = p.strip()
        words = p.split()
        if not (1 <= len(words) <= 4): continue
        if not NAMEY.match(p): continue
        if BANNED_WORDS.search(p): continue
        out.append(p)
    return out

def extract(text):
    investors, amount, company = [], None, None
    m = COMPANY_RE.search(text)
    if m: company = re.sub(r'\s+(?:Raises?|Lands?|Closes?|Secures?|Gets?|Bags?)$', '', m.group(1))
    m = AMOUNT_RE.search(text)
    if m: amount = m.group(1)
    for pat in INVESTOR_PATTERNS:
        for m in pat.finditer(text):
            investors.extend(split_investors(m.group(1)))
    clean = []
    for inv in investors:
        words = set(w.lower().strip('.,') for w in inv.split())
        if words & BAD_INVESTORS == words: continue
        if len(words & BAD_INVESTORS) == len(words): continue
        if any(bad == inv.lower() for bad in BAD_INVESTORS): continue
        clean.append(inv)
    return company, amount, clean

def main():
    ap = argparse.ArgumentParser(description="Find investors who funded startups like yours (TinyFish-powered).")
    ap.add_argument("description", help="one-line description of the startup")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--months", type=int, default=18, help="lookback window (default 18)")
    args = ap.parse_args()
    api_key = os.environ.get("TINYFISH_API_KEY")
    if not api_key:
        sys.exit("set TINYFISH_API_KEY (get one at https://agent.tinyfish.ai/api-keys)")
    kws = keywords(args.description)
    after = (date.today() - timedelta(days=30 * args.months)).isoformat()
    purpose = (f"Find startups similar to '{args.description}' that raised funding in the last "
               f"{args.months} months, and identify every investor (VC, angel, fund) named in the round.")
    queries = [
        " ".join(kws[:5]) + " startup raised funding",
        " ".join(kws[:4]) + " raises seed round led by",
        " ".join(kws[:6]) + " funding round investors",
        " ".join(kws[:3]) + " raised million " + str(date.today().year),
    ]
    investors = defaultdict(lambda: {"mentions": 0, "proof": [], "companies": set(), "amounts": []})
    seen_urls = set()
    for q in queries:
        try:
            data = search(api_key, q, purpose, after)
        except Exception as e:
            print(f"search failed for '{q}': {e}", file=sys.stderr); continue
        for r in data.get("results", []):
            url = r.get("url", "")
            if url in seen_urls: continue
            seen_urls.add(url)
            text = f"{r.get('title','')}. {r.get('snippet','')}"
            company, amount, invs = extract(text)
            for inv in invs:
                e = investors[inv]
                e["mentions"] += 1
                if company: e["companies"].add(company)
                if amount: e["amounts"].append(amount)
                e["proof"].append({"url": url, "title": r.get("title", ""), "date": r.get("date", "")})
    # merge common aliases: {"y": "y combinator", "sequoia": "sequoia capital", ...}
    canon = {}
    for name in investors:
        low = name.lower().strip()
        canon.setdefault(low, name)
    for low, full in list(canon.items()):
        for low2, full2 in canon.items():
            if low != low2 and (low2.startswith(low + " ") or low2.endswith(" " + low)):
                if len(full2) > len(full):
                    canon[low] = full2
    merged = {}
    for name, e in investors.items():
        target = canon[name.lower().strip()]
        if target in merged:
            m = merged[target]
            m["mentions"] += e["mentions"]; m["companies"] |= e["companies"]
            m["amounts"] += e["amounts"]; m["proof"] += e["proof"]
        else:
            merged[target] = e
    ranked = sorted(merged.items(), key=lambda kv: (-kv[1]["mentions"], -len(kv[1]["companies"])))
    out = []
    for name, e in ranked:
        proof, seen_p = [], set()
        for p in e["proof"]:
            if p["url"] not in seen_p:
                seen_p.add(p["url"]); proof.append(p)
        out.append({"investor": name, "mentions": e["mentions"],
                    "backed_similar": sorted(e["companies"])[:5],
                    "example_amounts": e["amounts"][:3], "proof": proof[:4]})
    if args.json:
        print(json.dumps({"startup": args.description, "since": after, "investors": out[:15]}, indent=2))
        return
    print(f"\nfunding radar: who funds startups like \"{args.description}\"")
    print(f"window: since {after} | {len(seen_urls)} sources checked | {len(out)} investors found\n")
    for i, inv in enumerate(out[:10], 1):
        cos = ", ".join(inv["backed_similar"][:3]) or "see sources"
        print(f"{i:2}. {inv['investor']}  ({inv['mentions']} mentions)")
        print(f"    backed: {cos}")
        for p in inv["proof"][:2]:
            d = f" [{p['date']}]" if p["date"] else ""
            print(f"    proof{d}: {p['url']}")
        print()

if __name__ == "__main__":
    main()
