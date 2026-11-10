# funding radar

who would actually fund your startup?

give it a one-line description of a startup. it finds companies like yours
that raised in the last 12-18 months, works out who backed them, and gives
you a ranked list of investors to approach - with proof for every match.

built on the [TinyFish Search API](https://docs.tinyfish.ai/search-api).
zero dependencies, just python 3.8+.

## use

```bash
export TINYFISH_API_KEY=sk-tinyfish-...   # get one at agent.tinyfish.ai/api-keys
python3 funding_radar.py "voice AI agents for outbound sales calls"
python3 funding_radar.py --json "devtool that reviews AI agent PRs"   # machine-readable
python3 funding_radar.py --months 12 "vertical SaaS for dental clinics"
```

## example (real output, "voice AI agents for outbound sales calls")

```
 1. Y Combinator  (3 mentions)
    backed: Cekura, Simple AI
    proof [Feb 10, 2026]: https://pulse2.com/simple-ai-14-million-seed-funding-raised-for-voice-ai-agent-platform/
 2. First Harmonic  (3 mentions)
    backed: Simple AI
    proof [Feb 12, 2026]: https://www.techinasia.com/news/combinatorbacked-ai-voice-startup-simple-nets-14m-seed
 3. Acrew Capital  (1 mentions)
    backed: Guava
    proof: https://www.businesswire.com/news/home/20261102236960/en/Guava-Lands-%2412.5-Million...
```

## how it works

1. pulls the distinctive keywords out of your description
2. runs 5 funding-news searches through TinyFish (freshness-bounded to your window)
3. extracts investors, amounts and company names from every result
4. ranks investors by mentions across independent sources
5. attaches the source URL and date for every single match - no proof, no listing

why this beats cold-calling a VC list: an investor who wired money into a
company like yours 8 months ago already believes in the category and still
has to deploy. pitch them while the thesis is hot.

built by [som](https://github.com/somdipto) for the tinyfish ambassador program.
