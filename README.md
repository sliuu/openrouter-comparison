# Eight models, six briefs

Source and published page for an experiment: eight frontier AI models from seven
labs were each given the same six website briefs, and the 48 results compared.

## The published site

`dist/` is the whole site — static HTML, one chart PNG, and 96 screenshots
compressed to JPG. No build step. Vercel serves it directly (`vercel.json` points
`outputDirectory` at it).

To rebuild it after editing the page:

```sh
python3 package.py analysis/blog_first_pass.html
```

That rewrites the page's `../sites/...` image paths to `img/`, compresses every
hero and full-page screenshot into `dist/img/`, copies the charts the page loads
by name, and zips the result.

## Pipeline

| Script | What it does |
| --- | --- |
| `generate.py` | Sends the six briefs to each model through OpenRouter |
| `screenshot.py` | Renders each generated site and captures hero + full-page PNGs |
| `analyze.py` / `analyze2.py` | Colour, type and similarity analysis; writes `analysis/` |
| `package.py` | Builds `dist/` from the page and the screenshots |

Python deps live in `.venv` (Playwright for screenshots, Pillow for images).

## What isn't in this repo

The raw `sites/**/*.png` screenshots (143 MB) and the `analysis/avg_*.png`
composites are gitignored — `screenshot.py` and `analyze2.py` regenerate them,
and the published page only needs the compressed copies in `dist/img/`.
