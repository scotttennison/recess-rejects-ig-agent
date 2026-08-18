#!/usr/bin/env python3
"""
One-off weekly novelty newsletter: makes fun of philosophy by comparing it to
kickball, rotating through a different philosopher/school each week
(newsletter/philosophy_themes.json, state in newsletter/philosophy_rotation_state.json).

This is a running joke sent to a single recipient, not part of the real
marketing newsletter — so unlike generate_newsletter.py (which only drafts
HTML for manual paste into Shopify Email), this one actually sends the email
itself via Gmail SMTP, since Shopify Email has no API for scripted sends.

Requires GEMINI_API_KEY (same one used elsewhere) and GMAIL_APP_PASSWORD (a
Gmail App Password for the sender account, not its regular password).
"""

import json
import os
import smtplib
import ssl
import subprocess
import sys
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from generate_newsletter import (  # noqa: E402
    BRAND_VOICE,
    GEMINI_API_KEY,
    list_gemini_text_candidates,
    render_html,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THEMES_PATH = os.path.join(REPO_ROOT, "newsletter", "philosophy_themes.json")
PRODUCTS_PATH = os.path.join(REPO_ROOT, "newsletter", "products.json")
STATE_PATH = os.path.join(REPO_ROOT, "newsletter", "philosophy_rotation_state.json")
STATE_REL_PATH = "newsletter/philosophy_rotation_state.json"

RECIPIENT = "stephenmarkfriesen@gmail.com"
SENDER = "recessrejectsstore@gmail.com"
FEATURED_PRODUCTS_PER_WEEK = 2


def pick_theme_and_products():
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

    with open(STATE_PATH, "w") as f:
        json.dump({"themeIndex": theme_index, "productIndex": next_product_index}, f, indent=2)

    return theme, featured


def commit_rotation_state():
    """Same pattern as generate_newsletter.py's commit_rotation_state — only
    persist the advanced rotation index after a successful send."""
    run = lambda *args: subprocess.run(args, cwd=REPO_ROOT, check=True)
    run("git", "config", "user.name", "recess-rejects-bot")
    run("git", "config", "user.email", "bot@recessrejects.local")
    run("git", "add", STATE_REL_PATH)

    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=REPO_ROOT)
    if diff.returncode == 0:
        print("No rotation state change to commit.", file=sys.stderr)
        return

    run("git", "commit", "-m", "Advance philosophy newsletter rotation")
    run("git", "pull", "--rebase", "--autostash")
    run("git", "push")


def call_gemini(candidates, theme, featured_products):
    product_lines = "\n".join(
        f"- {p['name']} (${p['price']}): {p['description']}" for p in featured_products
    )
    prompt = f"""{BRAND_VOICE}

This is a special one-off novelty newsletter, not the regular weekly one. The
whole bit is making fun of philosophy by comparing it to kickball. This week's
philosopher/school and its kickball angle: {theme}

Lean hard into the comparison in every section — real philosophical ideas or
quotes, deflated by a specific, absurd kickball/rec-league parallel. Keep the
Recess Rejects brand voice underneath it.

Featured products this week (write one blurb per product, tying it back to
the theme above where it fits naturally):
{product_lines}

Return ONLY raw JSON (no markdown fences, no preamble) matching this shape:
{{
  "subject_line": "short, funny, under 50 chars",
  "preview_text": "inbox preview line, under 90 chars",
  "headline": "big headline for top of email, riffs on the philosopher/theme",
  "intro_blurb": "1-2 sentences setting up the philosophy-vs-kickball bit",
  "promo_blurb": "1-2 sentences hyping free shipping over $50, tied to the bit",
  "product_blurbs": {{"<product name, exactly as given above>": "1 sentence pitch", ...}},
  "ig_blurb": "1-2 playful sentences, freeform, no real IG stats needed",
  "sign_off": "short sign-off line in brand voice, can reference the philosopher"
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


def send_email(subject, html):
    gmail_app_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_app_password:
        print("::error::GMAIL_APP_PASSWORD is not set")
        sys.exit(1)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = RECIPIENT
    msg.attach(MIMEText("View this email in an HTML-capable client.", "plain"))
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(SENDER, gmail_app_password)
        server.sendmail(SENDER, [RECIPIENT], msg.as_string())


def main():
    if not GEMINI_API_KEY:
        print("::error::GEMINI_API_KEY is not set")
        sys.exit(1)

    theme, featured_products = pick_theme_and_products()
    candidates = list_gemini_text_candidates()
    copy, model = call_gemini(candidates, theme, featured_products)
    notes = {
        "week_of": date.today().strftime("%B %-d, %Y"),
        "promo": "Free shipping on orders over $50 this week",
    }
    html = render_html(notes, copy, theme, featured_products)

    send_email(copy.get("subject_line") or f"Recess Rejects Philosophy Corner — {theme}", html)
    commit_rotation_state()

    print(f"Sent philosophy newsletter to {RECIPIENT}")
    print(f"Theme: {theme}")
    print(f"Subject: {copy.get('subject_line', '')}")
    print(f"Model used: {model}")


if __name__ == "__main__":
    main()
