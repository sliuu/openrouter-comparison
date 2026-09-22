"""
Screenshot every site in sites/ the same way, and save the page as the browser shows it.

Setup (once, inside the .venv):
  pip install playwright
  python -m playwright install chromium

Run from the same folder as generate.py:
  python screenshot.py               # skips sites already done
  python screenshot.py --force       # redo everything
  python screenshot.py --full-only   # redo only the full-page images (hero shots untouched)

Output, next to each site:
  <prompt>_hero.png       the first screen a visitor sees (1440x900)
  <prompt>_full.png       the whole page, top to bottom
  <prompt>_rendered.html  the page after its JavaScript ran (used by analyze.py)
"""
import glob, os, sys
from playwright.sync_api import sync_playwright

WIDTH, HEIGHT = 1440, 900   # a common laptop screen size
SETTLE_MS = 6000            # long enough for loading screens and entrance animations
FORCE = "--force" in sys.argv
FULL_ONLY = "--full-only" in sys.argv

# Many generated sites fade sections in as you scroll. Scrolling to the bottom
# first makes those sections visible in the full-page screenshot.
SCROLL_THROUGH = """
async () => {
  for (let y = 0; y < document.body.scrollHeight; y += 400) {
    window.scrollTo(0, y);
    await new Promise(r => setTimeout(r, 120));
  }
  window.scrollTo(0, 0);
}
"""

# Pinned nav bars (position: fixed or sticky) otherwise land in the middle of
# stitched full-page screenshots. Unpin them so they stay at the top of the page.
UNPIN = """
() => {
  for (const el of document.querySelectorAll('*')) {
    const pos = getComputedStyle(el).position;
    if (pos === 'fixed') el.style.setProperty('position', 'absolute', 'important');
    if (pos === 'sticky') el.style.setProperty('position', 'relative', 'important');
  }
}
"""

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
    for html in sorted(glob.glob("sites/*/*.html")):
        if html.endswith("_rendered.html"):
            continue
        base = html[:-5]
        outputs = [base + "_full.png"] if FULL_ONLY else \
                  [base + "_hero.png", base + "_full.png", base + "_rendered.html"]
        if not (FORCE or FULL_ONLY) and all(os.path.exists(o) for o in outputs):
            continue
        try:
            page.goto("file://" + os.path.abspath(html), wait_until="load", timeout=30000)
            page.wait_for_timeout(SETTLE_MS)
            if not FULL_ONLY:
                page.screenshot(path=base + "_hero.png")
            page.evaluate(SCROLL_THROUGH)
            page.wait_for_timeout(800)
            if not FULL_ONLY:
                # Save the page before unpinning, so the analysis sees it exactly as a visitor would
                with open(base + "_rendered.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
            page.evaluate(UNPIN)
            page.wait_for_timeout(300)
            page.screenshot(path=base + "_full.png", full_page=True)
            print("shot ", html)
        except Exception as e:
            print("FAIL ", html, e)
    browser.close()
