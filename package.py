"""
Package the blog into a self-contained folder you can upload or send anywhere.

Run from the project folder, inside the .venv (Pillow is already installed from analyze.py):
  python package.py                       # uses analysis/index.html
  python package.py path/to/your.html     # or point it at a different copy

Output:
  dist/index.html     the page, with image paths rewritten
  dist/img/           compressed JPGs: one hero shot per site
  dist.zip            the same folder, zipped, ready to send
To publish, upload the dist/ folder as-is (Netlify Drop, GitHub Pages, Vercel, or your portfolio host).
"""
import glob, os, re, shutil, sys
from PIL import Image

Image.MAX_IMAGE_PIXELS = None  # full-page screenshots can be very tall

SRC_HTML = sys.argv[1] if len(sys.argv) > 1 else "analysis/index.html"
OUT = "dist"
PROMPTS = {"saas", "candy", "techno", "law", "tea", "portfolio"}
SIZES = {"hero": (1440, 80)}  # max width, JPG quality

if not os.path.exists(SRC_HTML):
    sys.exit(f"Can't find {SRC_HTML}. Pass the path to your blog HTML file.")

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(f"{OUT}/img")

# 1. Compress every hero and full-page screenshot into dist/img/
count, total_in, total_out = 0, 0, 0
for png in sorted(glob.glob("sites/*/*_hero.png")):
    model = os.path.basename(os.path.dirname(png))
    prompt, kind = os.path.basename(png)[:-4].rsplit("_", 1)   # "techno_hero" -> techno, hero
    if prompt not in PROMPTS:
        continue
    max_w, quality = SIZES[kind]
    im = Image.open(png).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, round(im.height * max_w / im.width)), Image.LANCZOS)
    out = f"{OUT}/img/{model}__{prompt}_{kind}.jpg"
    im.save(out, quality=quality, optimize=True, progressive=True)
    count += 1
    total_in += os.path.getsize(png)
    total_out += os.path.getsize(out)

# 2. Point the page at the new images
html = open(SRC_HTML, encoding="utf-8").read()

# Charts the page loads by name from its own folder (data-file="font-chart.png")
src_dir = os.path.dirname(os.path.abspath(SRC_HTML))
for name in sorted(set(re.findall(r'data-file="([^"]+)"', html))):
    here = os.path.join(src_dir, name)
    if os.path.exists(here):
        shutil.copy2(here, f"{OUT}/{name}")
    else:
        print(f"WARNING: the page wants {name}, which isn't next to the HTML.")

swaps = {"../sites/${m}/${p}_hero.png": "img/${m}__${p}_hero.jpg"}
for old, new in swaps.items():
    if old not in html:
        print(f"WARNING: didn't find {old} in the HTML; images may not load. Tell Claude.")
    html = html.replace(old, new)
open(f"{OUT}/index.html", "w", encoding="utf-8").write(html)

# 3. Zip it
shutil.make_archive(OUT, "zip", OUT)

# 4. Report, and flag anything unfinished
mb = lambda b: f"{b / 1e6:.1f} MB"
print(f"{count} images: {mb(total_in)} -> {mb(total_out)}")
print(f"Wrote {OUT}/ and {OUT}.zip ({mb(os.path.getsize(OUT + '.zip'))})")
if count != 48:
    print(f"Note: expected 48 hero images (8 models x 6 briefs), found {count}.")
if "TODO" in html:
    print("Reminder: the page still contains a TODO placeholder.")
print(f"Preview it: open {OUT}/index.html in your browser.")
