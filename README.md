# funding radar

Give it one line about your startup. It gives you a ranked list of investors to pitch, with proof.

Built on four TinyFish endpoints:

1. **Datasets (TinySet)** builds a live dataset of similar companies that raised recently - name, round, amount, date, investors, source URL.
2. **Search** verifies each investor's recent deals and finds their contact/pitch route.
3. **Fetch** reads the investor pages to confirm the pitch route is real.
4. **Research** (deep run) names the partner who led each deal, typical cheque sizes, and stage focus.

## usage

```bash
export TINYFISH_API_KEY=...   # https://agent.tinyfish.ai/api-keys
python3 funding_radar.py "voice AI agents for outbound sales calls" --stage seed --country US --out report.md
```

options:
- `--months 18` - lookback window for funding rounds (default 18)
- `--dataset-id <id>` - reuse an existing TinySet dataset instead of building a new one
- `--research-md <file>` - attach a saved Research deep-run memo instead of launching a new run
- `--no-research` - skip the Research phase (fast)
- `--json` - machine-readable output

## demos

Three different startups, three real reports:

- [voice AI for outbound sales (US, seed)](demos/demo-voice-ai.md) - 15 companies, 12 ranked investors, full Research memo naming deal leads and cheques ([raw run](demos/research-voice-ai-run.json))
- [AI PR-review devtool (US, seed)](demos/demo-pr-review.md) - 11 companies, 12 ranked investors
- [dental clinic SaaS (India, seed)](demos/demo-india-dental-saas.md) - 14 companies, 12 ranked investors

Every company and deal claim links to a live source. Ranking rationale: number of similar companies backed, rounds led, deals in the last 9 months.

Built for the TinyBounties Funding Radar bounty by [@somdipto](https://github.com/somdipto).
