#!/usr/bin/env python3
"""
Generates the weekly Recess Rejects newsletter draft.

- Picks the next theme and next batch of featured products in rotation
  (newsletter/newsletter_themes.json, newsletter/products.json), persisting
  progress in newsletter/rotation-state.json the same way the Instagram
  pipeline persists config/rotation-state.json.
- Pulls manually-curated context from newsletter/weekly_notes.json (promo,
  IG highlights, extra notes)
- Calls Gemini for on-brand subject line + section copy (structured JSON output)
- Renders a brand-styled HTML email
- Prints everything to stdout, which the workflow redirects into
  $GITHUB_STEP_SUMMARY so it shows up right on the Actions run page,
  same spot you'd check a Buffer draft.

No secrets needed beyond GEMINI_API_KEY (same one used for the IG pipeline).

newsletter/products.json is a manual snapshot of the live Shopify catalog,
not a live API pull — refresh it whenever products are added, removed, or
repriced.
"""

import json
import os
import subprocess
import sys
from datetime import date

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("::error::GEMINI_API_KEY is not set")
    sys.exit(1)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES_PATH = os.path.join(REPO_ROOT, "newsletter", "weekly_notes.json")
THEMES_PATH = os.path.join(REPO_ROOT, "newsletter", "newsletter_themes.json")
PRODUCTS_PATH = os.path.join(REPO_ROOT, "newsletter", "products.json")
STATE_PATH = os.path.join(REPO_ROOT, "newsletter", "rotation-state.json")
STATE_REL_PATH = "newsletter/rotation-state.json"

FEATURED_PRODUCTS_PER_WEEK = 2

BRAND_VOICE = """
You are writing copy for Recess Rejects, an adult rec-league sports apparel brand.
Voice: "Grunt Style for adult rec league sports" - funny, self-aware, a little cocky,
loves the beer-league athlete identity. Slogan: "Last Picked. First to the Bar."
Never corporate, never earnest. Short punchy sentences. Rec league humor
(kickball, dodgeball, bocce, cornhole, pickleball, forfeits, post-game pitchers).

This newsletter should be genuinely funny, not just "on brand" - the kind of email
someone forwards to their team group chat because it made them laugh. Go for actual
jokes and punchlines, not just a wry tone:
- Use exaggeration and specific, absurd rec-league detail over generic humor
  ("sprinted 12 feet and needed a substitution" beats "not very athletic")
- Self-deprecating > mean-spirited, always
- Every section (headline, intro, promo, each product blurb, IG recap, sign-off)
  should land at least one real joke or punchline, not just describe the thing
- Vary the joke structure between sections so it doesn't all read the same
  (a one-liner, a mock-serious stat, a fake excuse, an aside in parentheses, etc.)
- If a line doesn't make you smirk while writing it, rewrite it
"""


EXCLUDED_TERMS = (
    "image", "vision", "omni", "audio", "tts", "live", "embedding",
    "aqa", "learnlm", "computer-use", "native-audio",
)


def list_gemini_text_candidates():
    """Check available Gemini models via the API rather than hardcoding one,
    since Google deprecates model names frequently. Returns candidates ordered
    newest/most-preferred first; excludes non-text-generation model variants."""
    resp = requests.get(
        f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}",
        timeout=30,
    )
    resp.raise_for_status()
    models = resp.json().get("models", [])
    candidates = [
        m["name"] for m in models
        if "generateContent" in m.get("supportedGenerationMethods", [])
        and "flash" in m["name"]
        and not any(term in m["name"] for term in EXCLUDED_TERMS)
    ]
    # Prefer stable names over "-preview"/"-exp" variants, then newest-looking first
    candidates.sort(key=lambda n: ("preview" in n or "exp" in n, n), reverse=True)
    if not candidates:
        raise RuntimeError("No suitable Gemini text model found")
    return candidates


def load_notes():
    with open(NOTES_PATH) as f:
        notes = json.load(f)
    if notes.get("week_of") in (None, "", "auto"):
        today = date.today()
        notes["week_of"] = today.strftime("%B %-d, %Y")
    return notes


def pick_theme_and_products():
    """Advances theme/product rotation state locally (not yet committed —
    that happens after generation succeeds, mirroring the IG pipeline)."""
    with open(THEMES_PATH) as f:
        themes = json.load(f)["themes"]
    with open(PRODUCTS_PATH) as f:
        products = json.load(f)["products"]

    try:
        with open(STATE_PATH) as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {"themeIndex": -1, "productIndex": -1}

    theme_index = (state.get("themeIndex", -1) + 1) % len(themes)
    theme = themes[theme_index]

    product_start = (state.get("productIndex", -1) + 1) % len(products)
    count = min(FEATURED_PRODUCTS_PER_WEEK, len(products))
    featured = [products[(product_start + i) % len(products)] for i in range(count)]
    next_product_index = (product_start + count - 1) % len(products)

    new_state = {"themeIndex": theme_index, "productIndex": next_product_index}
    with open(STATE_PATH, "w") as f:
        json.dump(new_state, f, indent=2)

    return theme, featured


def commit_rotation_state():
    """Commits and pushes the advanced rotation state, same pattern as the
    IG pipeline's saveImageAndGetUrl — run only after generation succeeds,
    so a failed run doesn't silently burn a rotation slot."""
    run = lambda *args: subprocess.run(args, cwd=REPO_ROOT, check=True)
    run("git", "config", "user.name", "recess-rejects-bot")
    run("git", "config", "user.email", "bot@recessrejects.local")
    run("git", "add", STATE_REL_PATH)

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT
    )
    if diff.returncode == 0:
        print("No rotation state change to commit.", file=sys.stderr)
        return

    run("git", "commit", "-m", "Advance newsletter theme/product rotation")
    run("git", "pull", "--rebase", "--autostash")
    run("git", "push")


def call_gemini(candidates, notes, theme, featured_products):
    product_lines = "\n".join(
        f"- {p['name']} (${p['price']}): {p['description']}" for p in featured_products
    )
    prompt = f"""{BRAND_VOICE}

Write copy for this week's Recess Rejects email newsletter.

This week's theme/angle: {theme}

Promo: {notes.get('promo')}

Featured products this week (write one blurb per product, tying it back to the theme above where it fits naturally):
{product_lines}

Instagram highlights: {'; '.join(notes.get('ig_highlights', []))}
Extra notes: {notes.get('extra_notes') or 'none'}

Return ONLY raw JSON (no markdown fences, no preamble) matching this shape:
{{
  "subject_line": "short, funny, under 50 chars",
  "preview_text": "inbox preview line, under 90 chars",
  "headline": "big headline for top of email, can riff on the week's theme",
  "intro_blurb": "1-2 sentences, brand voice, sets up the week's theme",
  "promo_blurb": "1-2 sentences hyping the promo",
  "product_blurbs": {{"<product name, exactly as given above>": "1 sentence pitch", ...}},
  "ig_blurb": "1-2 sentences recapping IG highlights, playful",
  "sign_off": "short sign-off line in brand voice"
}}
"""
    last_error = None
    for model in candidates:
        try:
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={GEMINI_API_KEY}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            return json.loads(text), model
        except (requests.exceptions.HTTPError, KeyError, IndexError, json.JSONDecodeError) as e:
            print(f"::warning::Model {model} failed ({e}), trying next candidate", file=sys.stderr)
            last_error = e
            continue
    raise RuntimeError(f"All Gemini model candidates failed. Last error: {last_error}")


def add_utm(url):
    """Tags outbound product links so newsletter-driven sessions show up
    under a real source in Shopify analytics instead of blank referrer —
    same gap found on the Instagram bio link."""
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}utm_source=newsletter&utm_medium=email"


def find_blurb(product_name, raw_blurbs):
    """Gemini doesn't always echo the product name key exactly as given
    (e.g. appends the price), so match by prefix rather than equality."""
    name_norm = product_name.strip().lower()
    for key, blurb in raw_blurbs.items():
        if key.strip().lower().startswith(name_norm):
            return blurb
    return ""


def render_html(notes, copy, theme, featured_products):
    raw_blurbs = copy.get("product_blurbs", {})
    products_html = "".join(
        f'<tr><td style="padding:12px 0;border-bottom:1px solid #e8e2d6;font-family:Arial,Helvetica,sans-serif;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="90" style="padding-right:16px;vertical-align:top;">'
        f'<a href="{add_utm(p["url"])}"><img src="{p["image"]}" width="90" height="90" alt="{p["name"]}" '
        f'style="display:block;border-radius:6px;object-fit:cover;"></a>'
        f'</td>'
        f'<td style="vertical-align:top;">'
        f'<a href="{add_utm(p["url"])}" style="text-decoration:none;">'
        f'<span style="color:#1a1a1a;font-size:15px;font-weight:bold;">{p["name"]}</span></a>'
        f'<br><span style="color:#c0392b;font-size:14px;font-weight:bold;">${p["price"]}</span>'
        f'<br><span style="color:#4a4a4a;font-size:14px;">{find_blurb(p["name"], raw_blurbs)}</span>'
        f'</td>'
        f'</tr></table></td></tr>'
        for p in featured_products
    )

    # NOTE: this is a fragment, not a full document. Paste only this into
    # Shopify Email's "Edit code" / HTML source box for a content section -
    # do NOT wrap it in <html>/<body>, Shopify strips that wrapper anyway and
    # taking it out ourselves avoids losing spacing along with it.
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2ece0;">
<tr><td align="center" style="text-align:center;padding:24px 0;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#fffdf8;border-radius:8px;margin:0 auto;">

<tr><td style="background-color:#CA4A39;padding:28px 32px;text-align:center;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="text-align:center;padding-bottom:10px;">
<img src="https://raw.githubusercontent.com/scotttennison/recess-rejects-ig-agent/main/assets/NameLogo.png" alt="RECESS REJECTS" width="220" style="display:block;margin:0 auto;max-width:220px;height:auto;border:0;">
</td></tr>
<tr><td align="center" style="text-align:center;font-family:Arial,Helvetica,sans-serif;color:#f2ece0;font-size:13px;letter-spacing:1px;">LAST PICKED. FIRST TO THE BAR.</td></tr>
</table>
</td></tr>

<tr><td style="padding:32px;font-family:Arial,Helvetica,sans-serif;">

<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="color:#1a1a1a;font-size:22px;font-weight:bold;padding-bottom:12px;">{copy.get('headline','')}</td></tr>
<tr><td style="color:#4a4a4a;font-size:15px;line-height:1.5;padding-bottom:24px;">{copy.get('intro_blurb','')}</td></tr>
</table>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2ece0;margin-bottom:24px;">
<tr><td style="border-left:4px solid #c0392b;padding:14px 18px;">
<span style="color:#1a1a1a;font-weight:bold;">This week:</span>
<span style="color:#4a4a4a;"> {copy.get('promo_blurb','')}</span>
</td></tr>
</table>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="color:#1a1a1a;font-size:16px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #1a1a1a;padding-bottom:8px;">On the Field</td></tr>
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
{products_html}
</table>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:28px;">
<tr><td style="color:#1a1a1a;font-size:16px;font-weight:bold;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #1a1a1a;padding-bottom:8px;">From the Sidelines</td></tr>
<tr><td style="color:#4a4a4a;font-size:15px;line-height:1.5;padding-top:12px;">{copy.get('ig_blurb','')}</td></tr>
</table>

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:28px;">
<tr><td style="color:#1a1a1a;font-size:15px;font-weight:bold;">{copy.get('sign_off','')}</td></tr>
</table>

</td></tr>

<tr><td style="background-color:#1a1a1a;padding:20px 32px;text-align:center;">
<span style="font-family:Arial,Helvetica,sans-serif;color:#f2ece0;font-size:12px;">Recess Rejects &middot; Apparel for adult rec league athletes</span>
</td></tr>

</table>
</td></tr>
</table>"""


def main():
    notes = load_notes()
    theme, featured_products = pick_theme_and_products()
    candidates = list_gemini_text_candidates()
    copy, model = call_gemini(candidates, notes, theme, featured_products)
    html = render_html(notes, copy, theme, featured_products)
    commit_rotation_state()

    print(f"## 📬 Newsletter Draft — Week of {notes['week_of']}\n")
    print(f"**Theme:** {theme}  ")
    print(f"**Featured products:** {', '.join(p['name'] for p in featured_products)}\n")
    print(f"**Subject line:** {copy.get('subject_line','')}  ")
    print(f"**Preview text:** {copy.get('preview_text','')}\n")
    print("### Copy-paste this into Shopify Email's HTML/code section (fragment only — don't wrap in <html>/<body>)\n")
    print("```html")
    print(html)
    print("```\n")
    print("---")
    print(f"_Model used: {model}_")


if __name__ == "__main__":
    main()
