"""
Analyze every generated site: fonts, colors, layout, and how similar the sites are.
No AI involved: it measures the code and the screenshots directly.

Run after generate.py and screenshot.py, from the same folder, inside the .venv:
  pip install pillow numpy
  python analyze.py

Output (in analysis/):
  data.json        everything the blog needs
  summary.txt      the headline numbers; paste this back to Claude
  thumbs/          small hero and full-page images for the blog
  avg_*.png        "average website" images (all sites, per model, per prompt)
"""
import colorsys, glob, json, os, re
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import unquote
import numpy as np
from PIL import Image

SITES, OUT = "sites", "analysis"
# Only these prompts are analyzed; anything else in sites/ is ignored.
PROMPTS_TO_INCLUDE = {"saas", "candy", "techno", "law", "portfolio"}

Image.MAX_IMAGE_PIXELS = None  # full-page screenshots can be very tall
rng = np.random.default_rng(0)

# ---------- Fonts: what each site asks for in its code ----------
SYSTEM = {"-apple-system", "blinkmacsystemfont", "system-ui", "ui-sans-serif", "segoe ui"}
GENERIC = {"sans-serif", "serif", "monospace", "cursive", "fantasy", "inherit",
           "initial", "unset", "ui-serif", "ui-monospace"}

def clean_font(value):
    first = " ".join(value.split(",")[0].strip().strip("'\"").split())
    low = first.lower()
    if not first or "(" in first or low in GENERIC or not re.search(r"[a-z]", low):
        return None
    if re.match(r"^[\d.]+(px|rem|em|%)?$", low):
        return None
    return "System UI" if low in SYSTEM else first

def fonts_in(html):
    found = []
    for q in re.findall(r"fonts\.googleapis\.com/css2?\?([^\"')\s>]+)", html):
        found += [unquote(f).replace("+", " ") for f in re.findall(r"family=([^&:]+)", q)]
    for v in re.findall(r"font-family\s*:\s*([^;{}]+)", html):
        found.append(clean_font(v))
    for v in re.findall(r"--[\w-]*font[\w-]*\s*:\s*([^;{}]+)", html):
        found.append(clean_font(v))
    for block in re.findall(r"fontFamily\s*:\s*\{(.*?)\}\s*[,}]", html, re.S):
        found += re.findall(r"\[\s*['\"]([^'\"]+)['\"]", block)
    return Counter(f.strip() for f in found if f and f.strip())

# ---------- Layout: the top-level sections of each page ----------
class Skeleton(HTMLParser):
    TAGS = {"section", "header", "footer", "nav", "form"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.sections, self.skip, self.words, self.grab = [], [], 0, 0, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.TAGS:
            if not self.stack:
                hint = f"{a.get('id') or ''} {a.get('class') or ''}".strip()
                self.sections.append({"tag": tag, "hint": hint, "heading": ""})
            self.stack.append(tag)
        elif tag in ("h1", "h2", "h3") and self.stack and not self.sections[-1]["heading"]:
            self.grab = []

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
            return
        if tag in ("h1", "h2", "h3") and self.grab is not None:
            self.sections[-1]["heading"] = " ".join("".join(self.grab).split())[:80]
            self.grab = None
        # Pop back to the matching tag, so one unclosed tag can't freeze the tracking.
        if tag in self.stack:
            while self.stack and self.stack.pop() != tag:
                pass

    def handle_data(self, data):
        if self.skip:
            return
        self.words += len(data.split())
        if self.grab is not None:
            self.grab.append(data)

# Keyword guesses for what a section is. Heuristic: good for patterns, not exact counts.
CATS = [("pricing", r"pric|\btiers?\b|per month"), ("testimonials", r"testimon|review|praise|what .* say"),
        ("faq", r"\bfaq|question"), ("team", r"\bteam\b|attorney|lawyer|founder|staff"),
        ("lineup", r"lineup|line-up|\bartists?\b|schedule|timetable"),
        ("gallery", r"gallery|portfolio|project|showcase|selected work"),
        ("about", r"about|story|mission|philosoph|ethos"),
        ("stats", r"\bstats?\b|metric|numbers|results"),
        ("features", r"feature|benefit|service|capabilit|practice|expertise|how it works"),
        ("products", r"\bmenu\b|product|shop|collection|flavo|candy|store"),
        ("contact", r"contact|\bcta\b|sign.?up|subscribe|newsletter|\bbook|consult|ticket|demo|get.?started"),
        ("loader", r"loader|loading|preload|splash"),
        ("hero", r"hero|banner|masthead")]

def categorize(sections):
    out = []
    for s in sections:
        if s["tag"] in ("nav", "footer"):
            out.append(s["tag"]); continue
        if s["tag"] == "form":
            out.append("contact"); continue
        text = f"{s['hint']} {s['heading']}".lower()
        cat = next((c for c, rx in CATS if re.search(rx, text)), "other")
        if cat == "other" and all(o in ("nav", "loader") for o in out):
            cat = "hero"  # first real section is almost always the hero
        out.append(cat)
    return out

# ---------- Colors: what the page actually looks like on screen ----------
HUES = [(15, "red"), (45, "orange"), (70, "yellow"), (160, "green"), (200, "teal"),
        (255, "blue"), (290, "purple"), (340, "pink"), (360, "red")]

def hue_name(h, s, v):
    if s < 0.15 or v < 0.12:
        return "neutral"
    return next(name for limit, name in HUES if h * 360 <= limit)

def palette(img, n=6):
    small = img.resize((160, 100))
    q = small.quantize(colors=n, method=0)  # 0 = median cut
    pal = q.getpalette()
    out = []
    for count, idx in sorted(q.getcolors(), reverse=True):
        r, g, b = pal[idx * 3: idx * 3 + 3]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        out.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "share": round(count / 16000, 3),
                    "hue": hue_name(h, s, v), "hue_deg": round(h * 360),
                    "sat": round(s, 2), "val": round(v, 2)})
    return out

def color_roles(pal):
    """Background = the biggest color; accent = the most vivid color that isn't tiny."""
    background = pal[0]
    vivid = [c for c in pal[1:] if c["share"] > 0.02 and c["hue"] != "neutral"]
    accent = max(vivid, key=lambda c: c["sat"] * c["val"]) if vivid else None
    hues = {c["hue"] for c in pal if c["share"] > 0.02 and c["hue"] != "neutral"}
    return {"background": background, "accent": accent, "hue_count": len(hues)}

def image_stats(img):
    small = img.resize((160, 100))
    hsv = np.asarray(small.convert("HSV"), dtype=np.float32) / 255
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lum = np.asarray(small.convert("L"), dtype=np.float32) / 255
    purple = ((h * 360 > 250) & (h * 360 < 300) & (s > 0.35) & (v > 0.25)).mean()
    return {"brightness": round(float(lum.mean()), 3), "dark": bool(lum.mean() < 0.35),
            "saturation": round(float(s.mean()), 3), "purple_share": round(float(purple), 3)}

def features(img):
    """A simple visual fingerprint: color mix plus the rough layout of light and dark."""
    hsv = np.asarray(img.resize((72, 45)).convert("HSV"))
    hist, _ = np.histogramdd(hsv.reshape(-1, 3).astype(float),
                             bins=(8, 3, 3), range=((0, 256),) * 3)
    color = hist.ravel() / (np.linalg.norm(hist) or 1)
    gray = np.asarray(img.resize((32, 20)).convert("L"), dtype=np.float32).ravel()
    gray = (gray - gray.mean()) / (gray.std() or 1)
    gray = gray / (np.linalg.norm(gray) or 1)
    return np.concatenate([color, gray])

# ---------- Similarity statistics ----------
def within(D, labels):
    L = np.array(labels)
    same = L[:, None] == L[None, :]
    np.fill_diagonal(same, False)
    return float(D[same].mean())

def grouping_test(D, labels, n=2000):
    """How similar are sites that share this label, vs. random pairings?"""
    obs = within(D, labels)
    null = np.array([within(D, rng.permutation(labels)) for _ in range(n)])
    return {"mean_distance": round(obs, 4), "random_baseline": round(float(null.mean()), 4),
            "p_value": float((null <= obs).mean())}

def mds(D):
    n = len(D)
    J = np.eye(n) - 1 / n
    w, v = np.linalg.eigh(-0.5 * J @ (D ** 2) @ J)
    idx = np.argsort(w)[::-1][:2]
    return v[:, idx] * np.sqrt(np.maximum(w[idx], 0))

# ---------- Main ----------
def main():
    os.makedirs(f"{OUT}/thumbs", exist_ok=True)
    sites, feats, heroes = [], [], []
    for html_path in sorted(glob.glob(f"{SITES}/*/*.html")):
        if html_path.endswith("_rendered.html"):
            continue
        base = html_path[:-5]
        parts = os.path.normpath(base).split(os.sep)
        model, prompt = parts[-2], parts[-1]
        if prompt not in PROMPTS_TO_INCLUDE:
            continue
        if not os.path.exists(base + "_hero.png"):
            print("skip (no screenshot):", html_path); continue
        html = open(html_path, encoding="utf-8", errors="replace").read()
        # The browser's version includes sections that JavaScript built after loading.
        rendered_path = base + "_rendered.html"
        rendered = open(rendered_path, encoding="utf-8", errors="replace").read() \
            if os.path.exists(rendered_path) else html
        meta = json.load(open(base + ".json")) if os.path.exists(base + ".json") else {}
        parser = Skeleton(); parser.feed(rendered)
        hero = Image.open(base + "_hero.png").convert("RGB")
        name = f"{model}__{prompt}"
        hero.resize((480, 300)).save(f"{OUT}/thumbs/{name}_hero.jpg", quality=80)
        if os.path.exists(base + "_full.png"):
            full = Image.open(base + "_full.png").convert("RGB")
            h = int(full.height * 480 / full.width)
            full.resize((480, h)).crop((0, 0, 480, min(h, 3840))).save(
                f"{OUT}/thumbs/{name}_full.jpg", quality=75)
        fonts = fonts_in(html)
        pal = palette(hero)
        sites.append({
            "model": model, "prompt": prompt, "id": name,
            "fonts": [f for f, _ in fonts.most_common()],
            "tailwind": "tailwindcss" in html,
            "gradients": len(re.findall(r"linear-gradient|radial-gradient|bg-gradient", html)),
            "three_column": bool(re.search(r"grid-cols-3|repeat\(\s*3\s*,", html)),
            "sections": categorize(parser.sections), "words": parser.words,
            "palette": pal, **color_roles(pal), **image_stats(hero),
            "meta": {k: meta.get(k) for k in ("seconds", "cost", "output_tokens",
                                             "thinking_tokens", "provider", "truncated")},
        })
        feats.append(features(hero))
        heroes.append(np.asarray(hero.resize((720, 450)), dtype=np.float32))

    if len(sites) < 4:
        return print("Not enough sites with screenshots yet.")
    models = sorted({s["model"] for s in sites})
    prompts = sorted({s["prompt"] for s in sites})

    # Average-website images
    def save_avg(idx, label):
        Image.fromarray(np.mean([heroes[i] for i in idx], axis=0).astype(np.uint8)).save(
            f"{OUT}/avg_{label}.png")
    save_avg(range(len(sites)), "all")
    for m in models:
        save_avg([i for i, s in enumerate(sites) if s["model"] == m], f"model_{m}")
    for p in prompts:
        save_avg([i for i, s in enumerate(sites) if s["prompt"] == p], f"prompt_{p}")

    # Pairwise visual distances, the 2D map, and the grouping tests
    F = np.array(feats)
    D = np.sqrt(((F[:, None, :] - F[None, :, :]) ** 2).sum(-1))
    for s, (x, y) in zip(sites, mds(D)):
        s["xy"] = [round(float(x), 4), round(float(y), 4)]
    by_model = grouping_test(D, [s["model"] for s in sites])
    by_prompt = grouping_test(D, [s["prompt"] for s in sites])

    # Per-model range (variety across its own sites) and signature (distinct from peers)
    scores = {}
    for m in models:
        mine = [i for i, s in enumerate(sites) if s["model"] == m]
        rng_ = np.mean([D[i, j] for i in mine for j in mine if i < j]) if len(mine) > 1 else 0
        sig = [D[i, j] for i in mine for j, t in enumerate(sites)
               if t["prompt"] == sites[i]["prompt"] and t["model"] != m]
        scores[m] = {"range": round(float(rng_), 4),
                     "signature": round(float(np.mean(sig)), 4) if sig else 0}

    # Closest look-alikes: same prompt across labs, and different prompts from one model
    pairs = [(D[i, j], i, j) for i in range(len(sites)) for j in range(i + 1, len(sites))]
    cross_lab = sorted(p for p in pairs if sites[p[1]]["prompt"] == sites[p[2]]["prompt"])[:5]
    same_model = sorted(p for p in pairs if sites[p[1]]["model"] == sites[p[2]]["model"])[:5]
    look = lambda ps: [{"a": sites[i]["id"], "b": sites[j]["id"], "distance": round(float(d), 4)}
                       for d, i, j in ps]

    font_census = Counter(f for s in sites for f in set(s["fonts"]))
    sequences = Counter(" > ".join(s["sections"]) for s in sites)
    data = {"models": models, "prompts": prompts, "sites": sites,
            "grouping": {"by_model": by_model, "by_prompt": by_prompt},
            "scores": scores, "font_census": font_census.most_common(),
            "lookalikes": {"same_prompt_across_labs": look(cross_lab),
                           "same_model_across_prompts": look(same_model)}}
    json.dump(data, open(f"{OUT}/data.json", "w"), indent=1)

    # Human-readable summary
    n = len(sites)
    pct = lambda k: f"{sum(1 for s in sites if s[k]) / n:.0%}"
    lines = [f"{n} sites, {len(models)} models, {len(prompts)} prompts", "",
             "GROUPING (lower distance = more alike; p < 0.05 = more alike than chance)",
             f"  same model, different prompts: {by_model}",
             f"  same prompt, different models: {by_prompt}", "",
             "MODEL SCORES (range = variety across own sites; signature = distinct from peers)"]
    lines += [f"  {m:22} range {v['range']:.3f}   signature {v['signature']:.3f}"
              for m, v in scores.items()]
    lines += ["", "FONTS (number of sites declaring each)"]
    lines += [f"  {c:3}  {f}" for f, c in font_census.most_common(15)]
    lines += ["", f"Dark hero: {pct('dark')}   Tailwind: {pct('tailwind')}   "
              f"3-column grid: {pct('three_column')}   "
              f"Any purple (>5% of hero): {sum(s['purple_share'] > .05 for s in sites) / n:.0%}", "",
              "ACCENT HUES (most vivid major color in each hero)"]
    accents = Counter(s["accent"]["hue"] if s["accent"] else "none" for s in sites)
    lines += [f"  {c:3}  {h}" for h, c in accents.most_common()]
    lines += ["", "MOST COMMON SECTION SEQUENCES"]
    lines += [f"  {c:3}  {seq}" for seq, c in sequences.most_common(5)]
    lines += ["", "CLOSEST LOOK-ALIKES, same prompt across labs"]
    lines += [f"  {x['distance']:.3f}  {x['a']}  ~  {x['b']}" for x in data["lookalikes"]["same_prompt_across_labs"]]
    lines += ["", "CLOSEST LOOK-ALIKES, one model across different prompts"]
    lines += [f"  {x['distance']:.3f}  {x['a']}  ~  {x['b']}" for x in data["lookalikes"]["same_model_across_prompts"]]
    open(f"{OUT}/summary.txt", "w").write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main()
