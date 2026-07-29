#!/usr/bin/env python3
"""
Generates the weekly Recess Rejects newsletter draft.

- Pulls context from newsletter/weekly_notes.json
- Calls Gemini for on-brand subject line + section copy (structured JSON output)
- Renders a brand-styled HTML email
- Prints everything to stdout, which the workflow redirects into
  $GITHUB_STEP_SUMMARY so it shows up right on the Actions run page,
  same spot you'd check a Buffer draft.

No secrets needed beyond GEMINI_API_KEY (same one used for the IG pipeline).
"""

import json
import os
import sys
from datetime import date, timedelta

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    print("::error::GEMINI_API_KEY is not set")
    sys.exit(1)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTES_PATH = os.path.join(REPO_ROOT, "newsletter", "weekly_notes.json")

BRAND_VOICE = """
You are writing copy for Recess Rejects, an adult rec-league sports apparel brand.
Voice: "Grunt Style for adult rec league sports" - funny, self-aware, a little cocky,
loves the beer-league athlete identity. Slogan: "Last Picked. First to the Bar."
Never corporate, never earnest. Short punchy sentences. Rec league humor
(kickball, dodgeball, bocce, cornhole, pickleball, forfeits, post-game pitchers).
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


def call_gemini(candidates, notes):
    prompt = f"""{BRAND_VOICE}

Write copy for this week's Recess Rejects email newsletter using this week's inputs:

Promo: {notes.get('promo')}
Featured products: {', '.join(notes.get('featured_products', []))}
Instagram highlights: {'; '.join(notes.get('ig_highlights', []))}
Extra notes: {notes.get('extra_notes') or 'none'}

Return ONLY raw JSON (no markdown fences, no preamble) matching this shape:
{{
  "subject_line": "short, funny, under 50 chars",
  "preview_text": "inbox preview line, under 90 chars",
  "headline": "big headline for top of email",
  "intro_blurb": "1-2 sentences, brand voice, sets up the week",
  "promo_blurb": "1-2 sentences hyping the promo",
  "product_blurbs": {{"<product name>": "1 sentence pitch", ...}},
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


def render_html(notes, copy):
    products_html = "".join(
        f'<tr><td style="padding:12px 0;border-bottom:1px solid #e8e2d6;font-family:Arial,Helvetica,sans-serif;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td>'
        f'<span style="color:#1a1a1a;font-size:15px;font-weight:bold;">{name}</span>'
        f'</td></tr><tr><td style="padding-top:4px;">'
        f'<span style="color:#4a4a4a;font-size:14px;">{blurb}</span>'
        f'</td></tr></table></td></tr>'
        for name, blurb in copy.get("product_blurbs", {}).items()
    )

    # NOTE: this is a fragment, not a full document. Paste only this into
    # Shopify Email's "Edit code" / HTML source box for a content section -
    # do NOT wrap it in <html>/<body>, Shopify strips that wrapper anyway and
    # taking it out ourselves avoids losing spacing along with it.
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2ece0;">
<tr><td align="center" style="padding:24px 0;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#fffdf8;border-radius:8px;">

<tr><td style="background-color:#c0392b;padding:28px 32px;text-align:center;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="font-family:Arial,Helvetica,sans-serif;color:#fffdf8;font-size:26px;font-weight:bold;letter-spacing:0.5px;padding-bottom:6px;">RECESS REJECTS</td></tr>
<tr><td align="center" style="font-family:Arial,Helvetica,sans-serif;color:#f2ece0;font-size:13px;letter-spacing:1px;">LAST PICKED. FIRST TO THE BAR.</td></tr>
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
    candidates = list_gemini_text_candidates()
    copy, model = call_gemini(candidates, notes)
    html = render_html(notes, copy)

    print(f"## 📬 Newsletter Draft — Week of {notes['week_of']}\n")
    print(f"**Subject line:** {copy.get('subject_line','')}  ")
    print(f"**Preview text:** {copy.get('preview_text','')}\n")
    print("### Copy-paste this into Shopify Email's HTML/code section (fragment only \u2014 don't wrap in <html>/<body>)\n")
    print("```html")
    print(html)
    print("```\n")
    print("---")
    print(f"_Model used: {model}_")


if __name__ == "__main__":
    main()
