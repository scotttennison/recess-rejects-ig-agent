# Recess Rejects — Instagram Content Agent

Drafts Instagram posts for the kickball line: Claude writes the caption, Gemini (Nano Banana) generates the image, and it lands in **Buffer as a draft**. Nothing posts to Instagram without you reviewing it in Buffer and hitting schedule/send.

Runs automatically 3x/week (Mon/Wed/Fri), and you can also trigger a one-off post about any topic whenever you want.

---

## One-time setup

### 1. Create a GitHub repo
- Create a new **private** repo (e.g. `recess-rejects-ig-agent`)
- Push these files into it (or ask me to help you do this via git commands)

### 2. Connect Buffer
- Make sure your Recess Rejects Instagram account is added to Buffer as a **Business/Creator** account (personal IG accounts can't be posted to via API)
- Go to your Buffer account settings → generate a personal **API key** (only an organization owner can do this)
- Find your **channel ID** for the Instagram channel — the easiest way is to ask Claude/ChatGPT connected to Buffer's API, or check Buffer's API docs playground for a `channels` query against your account
- Set the Instagram channel's permission to **"Requires Approval"** in Buffer, so anything created via API — even without `saveToDraft` — lands as a draft as a safety net

### 3. Get your API keys
- **Anthropic (Claude) API key** — from console.anthropic.com
- **Gemini API key** — from Google AI Studio (aistudio.google.com)
- **Buffer API key** — from step 2 above

### 4. Add secrets to GitHub
In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add all four:
- `ANTHROPIC_API_KEY`
- `GEMINI_API_KEY`
- `BUFFER_API_KEY`
- `BUFFER_CHANNEL_ID`

### 5. Test it
Go to the **Actions** tab → "Recess Rejects — Kickball Content Agent" → **Run workflow**. Type a topic (e.g. "kickball rain delay") or leave it blank to test the auto-rotation, then run it.

Check the workflow logs for errors, and check Buffer for the resulting draft.

---

## Ongoing use

- **Scheduled posts**: happen automatically Mon/Wed/Fri at 9am Pacific (adjust the cron line in `.github/workflows/kickball-content.yml` if you want a different cadence/time)
- **One-off posts**: Actions tab → Run workflow → type your topic
- **Review**: open Buffer, check the draft, edit if needed, hit schedule or post now
- **Add new content themes**: edit `config/themes.json` any time
- **Expand to new sports later**: update `config/brand.json`'s `currentSportFocus` field once new products are live, and add new themes

---

## Files

| File | Purpose |
|---|---|
| `scripts/generate-post.mjs` | Main logic: caption → image → Buffer draft |
| `config/brand.json` | Brand voice, tone rules, visual style guide |
| `config/themes.json` | Rotation of kickball content ideas |
| `config/rotation-state.json` | Auto-generated, tracks which theme is next (don't edit manually) |
| `.github/workflows/kickball-content.yml` | Schedule + manual trigger definition |

---

## Notes / things to watch

- Gemini image generation costs ~$0.039/image at time of writing — negligible for 3x/week
- Buffer's free plan covers this fine (3 channels, API access included)
- Generated images get committed into `generated-images/` in this repo so Buffer can fetch them from a public URL — feel free to periodically clean out old ones you don't need
- If Buffer changes their API again (they've done a couple of migrations recently), the error message from the workflow log will usually point at what changed
