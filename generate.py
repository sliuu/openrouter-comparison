"""
Send the same website prompts to several models via OpenRouter and save each result.

Setup:
  1. Get a key at https://openrouter.ai/keys and add credit (the balance caps your spend).
  2. export OPENROUTER_API_KEY=sk-or-...
  3. python3 generate.py --check    # verify model names first
  4. python3 generate.py --test     # 1 prompt x all models; prints the cost
  5. python3 generate.py            # full run; re-running skips finished sites

Output:
  sites/<model>/<prompt>.html   the website
  sites/<model>/<prompt>.json   time, tokens, cost, and whether it was cut off
No third-party packages needed (standard library only).
"""
import json, os, re, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

API = "https://openrouter.ai/api/v1"
KEY = os.environ.get("OPENROUTER_API_KEY", "")
OUT = "sites"

# Label -> OpenRouter model slug. Slugs are guesses: run --check to confirm them.
MODELS = {
         "glm-5.3":             "z-ai/glm-5.3",
    "kimi-k3":             "moonshotai/kimi-k3",
    "muse-spark-1.3":      "meta/muse-spark-1.3",
    "gpt-6-astra":         "openai/gpt-6-astra",
    "gemini-3.8-flash":    "google/gemini-3.8-flash",
    "claude-fable-5.1":    "anthropic/claude-fable-5.1",
    "deepseek-v4.1-flash": "deepseek/deepseek-v4.1-flash",
     "claude-opus-5":       "anthropic/claude-opus-5",
}

# Output ceiling per model (default 32,000). Thinking tokens count toward it.
# Heavy thinkers need more room, or their sites get cut off or come back empty.
MAX_TOKENS = {"kimi-k3": 100000, "claude-fable-5.1": 64000,
              "deepseek-v4.1-flash": 64000, "glm-5.3": 100000}

PROMPTS = {
    "saas":      "Create a website for Connected, a B2B AI platform that helps marketing teams plan, write, and launch campaigns using AI agents.",
    "candy":     "Create a website for Sweet Summer Days, an online boutique for healthy-ish candy made with real sugar, for kids and adults.",
    "techno":    "Create a website for Entanglement, a 3-day underground techno festival set in a forest outside Amsterdam.",
    "law":       "Create a website for Harlow & Pierce, a modern law firm specializing in accident and injury law in Michigan.",
    "tea":       "Create a website for Koyo, a traditional Japanese tea house adapted for modern life and cafe-sitting in San Francisco.",
    "portfolio": "Create a website for Jenny Waltz, a high-end interior designer taking on clients in New York City.",
}

# Neutral instructions: no style hints.
SYSTEM = ("You are an expert designer and frontend developer. Return one complete, self-contained "
          "HTML file with all CSS and JavaScript inline. Output only the code.")


def call(path, body=None):
    req = urllib.request.Request(
        API + path,
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        # Surface OpenRouter's actual error message instead of a bare status code.
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")


def check():
    """Confirm each slug exists; suggest close matches if not."""
    ids = [m["id"] for m in call("/models")["data"]]
    for label, slug in MODELS.items():
        if slug in ids:
            print(f"OK       {label:22} {slug}")
        else:
            words = [w for w in re.split(r"[-/. ]", label) if len(w) > 1]
            hits = [i for i in ids if sum(w in i for w in words) >= 2]
            print(f"MISSING  {label:22} {slug}\n         try: {hits[:5] or 'search openrouter.ai/models'}")


def extract_html(text):
    """Take the longest code block if there is one, then trim to the HTML itself."""
    blocks = re.findall(r"```[a-zA-Z]*\s*\n(.*?)```", text, re.S)
    if blocks:
        text = max(blocks, key=len)
    start = re.search(r"<!DOCTYPE|<html", text, re.I)
    return text[start.start():].strip() if start else text.strip()


def run(job):
    label, pid = job
    base = f"{OUT}/{label}/{pid}"
    if os.path.exists(base + ".html"):
        return None
    os.makedirs(os.path.dirname(base), exist_ok=True)
    for attempt in range(3):
        t0 = time.time()
        try:
            res = call("/chat/completions", {
                "model": MODELS[label],
                "messages": [{"role": "system", "content": SYSTEM},
                             {"role": "user", "content": PROMPTS[pid]}],
                "max_tokens": MAX_TOKENS.get(label, 32000),
                "usage": {"include": True},
            })
            if "error" in res:
                raise RuntimeError(res["error"])
            choice = res["choices"][0]
            raw = choice["message"].get("content") or ""
            html = extract_html(raw)
            if "<html" not in html.lower():
                # Save what came back so the failure can be diagnosed.
                with open(base + ".failed.txt", "w", encoding="utf-8") as f:
                    f.write(f"finish_reason: {choice.get('finish_reason')}\n"
                            f"usage: {json.dumps(res.get('usage'))}\n\n{raw}")
                raise RuntimeError(f"no HTML (finish_reason={choice.get('finish_reason')}, "
                                   f"reply was {len(raw)} characters; see {base}.failed.txt)")
            u = res.get("usage", {})
            details = u.get("completion_tokens_details") or {}
            meta = {"model": label, "slug": MODELS[label], "prompt": pid,
                    "returned_model": res.get("model"), "provider": res.get("provider"),
                    "started_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t0)),
                    "seconds": round(time.time() - t0),
                    "prompt_tokens": u.get("prompt_tokens"),
                    "output_tokens": u.get("completion_tokens"),
                    "thinking_tokens": details.get("reasoning_tokens"),
                    "html_chars": len(html), "cost": u.get("cost"),
                    "finish_reason": choice.get("finish_reason"),
                    "truncated": choice.get("finish_reason") == "length"}
            # Save the untouched reply too, for debugging odd-looking sites.
            with open(base + ".raw.txt", "w", encoding="utf-8") as f:
                f.write(raw)
            # Write the metadata first, then the HTML, so a finished .html always has its .json.
            with open(base + ".json", "w") as f:
                json.dump(meta, f, indent=2)
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(html)
            flag = "  (CUT OFF: hit length limit)" if meta["truncated"] else ""
            print(f"done  {label:22} {pid:13} {meta['seconds']:5}s  ${meta['cost'] or 0:.3f}{flag}")
            return meta
        except Exception as e:
            print(f"retry {label} {pid} ({attempt + 1}/3): {e}")
            time.sleep(5 * (attempt + 1))
    print(f"FAIL  {label} {pid}")


if __name__ == "__main__":
    if not KEY:
        sys.exit("Set OPENROUTER_API_KEY first.")
    if "--check" in sys.argv:
        check()
        sys.exit()
    prompts = list(PROMPTS)[:1] if "--test" in sys.argv else list(PROMPTS)
    # Prompt-major order spreads parallel requests across providers instead of
    # hitting one model several times at once.
    jobs = [(m, p) for p in prompts for m in MODELS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = [r for r in pool.map(run, jobs) if r]
    cost = sum(r["cost"] or 0 for r in results)
    print(f"\n{len(results)} new sites, ${cost:.2f} this run.")
    if "--test" in sys.argv and results:
        print(f"Estimated full run ({len(PROMPTS)} prompts): about ${cost * len(PROMPTS):.2f}")
