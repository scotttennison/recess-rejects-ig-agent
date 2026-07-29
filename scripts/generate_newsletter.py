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


def pick_gemini_model():
    """Check available Gemini models via the API rather than hardcoding one,
    since Google deprecates model names frequently."""
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
        and "image" not in m["name"]
    ]
    # Prefer the newest-looking flash text model
    candidates.sort(reverse=True)
    if not candidates:
        raise RuntimeError("No suitable Gemini text model found")
    return candidates[0]


def load_notes():
    with open(NOTES_PATH) as f:
        notes = json.load(f)
    if notes.get("week_of") in (None, "", "auto"):
        today = date.today()
        notes["week_of"] = today.strftime("%B %-d, %Y")
    return notes


def call_gemini(model, notes):
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
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent?key={GEMINI_API_KEY}",
        json={"contents": [{"parts": [{"text": prompt}]}]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def render_html(notes, copy):
    products_html = "".join(
        f'<tr><td style="padding:12px 0;border-bottom:1px solid #e8e2d6;">'
        f'<strong style="color:#1a1a1a;">{name}</strong><br>'
        f'<span style="color:#4a4a4a;">{blurb}</span></td></tr>'
        for name, blurb in copy.get("product_blurbs", {}).items()
    )

    return f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background-color:#f2ece0;font-family:Arial,Helvetica,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2ece0;padding:24px 0;">
    <tr>
      <td align="center">
        <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background-color:#fffdf8;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="background-color:#c0392b;padding:28px 32px;text-align:center;">
              <div style="color:#fffdf8;font-size:26px;font-weight:bold;letter-spacing:0.5px;">RECESS REJECTS</div>
              <div style="color:#f2ece0;font-size:13px;letter-spacing:1px;margin-top:4px;">LAST PICKED. FIRST TO THE BAR.</div>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;">
              <h1 style="color:#1a1a1a;font-size:22px;margin:0 0 12px;">{copy.get('headline','')}</h1>
              <p style="color:#4a4a4a;font-size:15px;line-height:1.5;margin:0 0 24px;">{copy.get('intro_blurb','')}</p>

              <div style="background-color:#f2ece0;border-left:4px solid #c0392b;padding:14px 18px;margin-bottom:24px;">
                <strong style="color:#1a1a1a;">This week:</strong>
                <span style="color:#4a4a4a;"> {copy.get('promo_blurb','')}</span>
              </div>

              <h2 style="color:#1a1a1a;font-size:16px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #1a1a1a;padding-bottom:8px;">On the Field</h2>
              <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                {products_html}
              </table>

              <h2 style="color:#1a1a1a;font-size:16px;text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid #1a1a1a;padding-bottom:8px;margin-top:28px;">From the Sidelines</h2>
              <p style="color:#4a4a4a;font-size:15px;line-height:1.5;">{copy.get('ig_blurb','')}</p>

              <p style="color:#1a1a1a;font-size:15px;font-weight:bold;margin-top:28px;">{copy.get('sign_off','')}</p>
            </td>
          </tr>
          <tr>
            <td style="background-color:#1a1a1a;padding:20px 32px;text-align:center;">
              <span style="color:#f2ece0;font-size:12px;">Recess Rejects &middot; Apparel for adult rec league athletes</span>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def main():
    notes = load_notes()
    model = pick_gemini_model()
    copy = call_gemini(model, notes)
    html = render_html(notes, copy)

    print(f"## 📬 Newsletter Draft — Week of {notes['week_of']}\n")
    print(f"**Subject line:** {copy.get('subject_line','')}  ")
    print(f"**Preview text:** {copy.get('preview_text','')}\n")
    print("### Copy-paste this into Shopify Email (HTML source view)\n")
    print("```html")
    print(html)
    print("```\n")
    print("---")
    print(f"_Model used: {model}_")


if __name__ == "__main__":
    main()
