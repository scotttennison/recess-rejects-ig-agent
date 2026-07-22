#!/usr/bin/env node
/**
 * Recess Rejects — Instagram content agent
 *
 * Flow:
 *   1. Pick a theme (from CLI arg for one-offs, or next-in-rotation for scheduled runs)
 *   2. Ask Gemini to write a caption + hashtags in brand voice
 *   3. Ask Gemini (Nano Banana) to generate an accompanying scene image
 *   3b. Ask Gemini to fix the tongue against the real logo reference
 *   4. Commit the image to this repo (so it has a public raw.githubusercontent.com URL)
 *   5. Push a DRAFT post to Buffer via its GraphQL API (nothing goes live automatically)
 *
 * Required environment variables (set as GitHub Actions secrets):
 *   GEMINI_API_KEY      - Google AI Studio / Gemini API key (used for both caption text and image generation)
 *   BUFFER_API_KEY      - Buffer personal API key (org owner only)
 *   BUFFER_CHANNEL_ID   - Buffer channel ID for the Recess Rejects Instagram account
 *   GITHUB_REPOSITORY   - auto-provided by GitHub Actions, used to build the raw image URL
 */

import fs from "node:fs/promises";
import path from "node:path";
import { execSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");

const GEMINI_API_KEY = process.env.GEMINI_API_KEY;
const BUFFER_API_KEY = process.env.BUFFER_API_KEY;
const BUFFER_CHANNEL_ID = process.env.BUFFER_CHANNEL_ID;
const GITHUB_REPOSITORY = process.env.GITHUB_REPOSITORY;
const GITHUB_REF_NAME = process.env.GITHUB_REF_NAME || "main";

function requireEnv(name, value) {
  if (!value) {
    console.error(`Missing required environment variable: ${name}`);
    process.exit(1);
  }
}

for (const [name, value] of Object.entries({
  GEMINI_API_KEY,
  BUFFER_API_KEY,
  BUFFER_CHANNEL_ID,
  GITHUB_REPOSITORY,
})) {
  requireEnv(name, value);
}

async function loadJson(relPath) {
  const raw = await fs.readFile(path.join(ROOT, relPath), "utf8");
  return JSON.parse(raw);
}

// ---------- 1. Pick a theme ----------

async function pickTheme() {
  const cliTopic = process.argv.slice(2).join(" ").trim();
  if (cliTopic) {
    return { theme: cliTopic, source: "manual" };
  }

  const themesConfig = await loadJson("config/themes.json");
  const statePath = path.join(ROOT, "config", "rotation-state.json");

  let state = { lastIndex: -1 };
  try {
    state = JSON.parse(await fs.readFile(statePath, "utf8"));
  } catch {
    // no state file yet, start fresh
  }

  const nextIndex = (state.lastIndex + 1) % themesConfig.themes.length;
  await fs.writeFile(statePath, JSON.stringify({ lastIndex: nextIndex }, null, 2));

  return { theme: themesConfig.themes[nextIndex], source: "scheduled" };
}

// ---------- 2. Generate caption via Gemini (text model) ----------

async function generateCaption(brand, theme) {
  const systemPrompt = `You are the social media voice of ${brand.brandName}, a rec-league apparel brand.
Tagline: "${brand.tagline}"
Positioning: ${brand.positioning}
Audience: ${brand.audience}
Current sport focus: ${brand.currentSportFocus.join(", ")} only — do not reference other sports.

Voice guidelines:
${brand.voice.doList.map((d) => `- ${d}`).join("\n")}

Avoid:
${brand.voice.avoidList.map((d) => `- ${d}`).join("\n")}

Write ONE Instagram caption for the theme given by the user. Return ONLY valid JSON, no markdown fences, no preamble, in this exact shape:
{"caption": "...", "hashtags": ["#tag1", "#tag2"], "imagePrompt": "a detailed visual description for an image generator, incorporating the brand mascot and color palette where it fits"}`;

  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
      },
      body: JSON.stringify({
        systemInstruction: { parts: [{ text: systemPrompt }] },
        contents: [{ parts: [{ text: `Theme: ${theme}` }] }],
        generationConfig: { responseMimeType: "application/json" },
      }),
    }
  );

  if (!res.ok) {
    throw new Error(`Gemini text API error: ${res.status} ${await res.text()}`);
  }

  const data = await res.json();
  const parts = data.candidates?.[0]?.content?.parts || [];
  const textPart = parts.find((p) => p.text);

  if (!textPart) {
    throw new Error(`Gemini text response had no text part: ${JSON.stringify(data)}`);
  }

  const cleaned = textPart.text.trim().replace(/^```json\s*|\s*```$/g, "");
  return JSON.parse(cleaned);
}

// ---------- 3. Generate scene image via Gemini (Nano Banana) ----------

async function generateImage(brand, imagePrompt) {
  const fullPrompt = `Image 1 attached is the official, exact mascot character design for this brand — a red kickball character. Its tongue is shaped exactly like a human foot sticking out of its mouth: it has a distinct heel, an arch, and five small rounded toes at the end, not a normal flat tongue. This foot-shaped tongue is the single most important and unusual identifying feature of the mascot — do not simplify it into a regular tongue shape. Copy the mascot's face, this exact foot-shaped tongue, and its color exactly as shown in image 1, unchanged. Only change the pose, body position, and surrounding scene to fit this new context: ${imagePrompt}. Style: ${brand.visualStyle.imageGuidance}. Color palette: ${brand.visualStyle.colorPalette.join(", ")}. Square 1:1 aspect ratio for Instagram.`;

  const logoPath = path.join(ROOT, "assets", "NoWordsLogo.png");
  const logoBuffer = await fs.readFile(logoPath);
  const logoBase64 = logoBuffer.toString("base64");

  console.log("---- FULL SCENE GENERATION PROMPT ----");
  console.log(fullPrompt);
  console.log("---------------------------------------");

  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
      },
      body: JSON.stringify({
        contents: [
          {
            parts: [
              { inlineData: { mimeType: "image/png", data: logoBase64 } },
              { text: fullPrompt },
            ],
          },
        ],
        generationConfig: { responseModalities: ["TEXT", "IMAGE"] },
      }),
    }
  );

  if (!res.ok) {
    throw new Error(`Gemini API error: ${res.status} ${await res.text()}`);
  }

  const data = await res.json();
  const parts = data.candidates?.[0]?.content?.parts || [];
  const imagePart = parts.find((p) => p.inlineData);

  if (!imagePart) {
    throw new Error("Gemini response did not contain image data.");
  }

  return Buffer.from(imagePart.inlineData.data, "base64");
}

// ---------- 3b. Fix the tongue against the reference logo ----------

async function fixTongue(sceneImageBuffer, logoBuffer) {
  const sceneBase64 = sceneImageBuffer.toString("base64");
  const logoBase64 = logoBuffer.toString("base64");

  const editPrompt = `Image 1 is a cartoon illustration with a mascot character. Image 2 is the official reference showing the mascot's correct tongue design: a tongue shaped exactly like a human foot, with a heel, arch, and five distinct rounded toes. Edit image 1 so that the mascot's tongue is replaced with this exact foot-shaped tongue design from image 2 — heel, arch, and five toes clearly visible. Do not change anything else in image 1: keep the same pose, background, composition, colors, and text exactly as they are. Only fix the tongue shape.`;

  console.log("---- FULL TONGUE-FIX PROMPT ----");
  console.log(editPrompt);
  console.log("---------------------------------");

  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
      },
      body: JSON.stringify({
        contents: [
          {
            parts: [
              { inlineData: { mimeType: "image/png", data: sceneBase64 } },
              { inlineData: { mimeType: "image/png", data: logoBase64 } },
              { text: editPrompt },
            ],
          },
        ],
        generationConfig: { responseModalities: ["TEXT", "IMAGE"] },
      }),
    }
  );

  if (!res.ok) {
    throw new Error(`Gemini tongue-fix API error: ${res.status} ${await res.text()}`);
  }

  const data = await res.json();
  const parts = data.candidates?.[0]?.content?.parts || [];
  const imagePart = parts.find((p) => p.inlineData);

  if (!imagePart) {
    console.warn("Tongue fix pass returned no image — using original scene image instead.");
    return sceneImageBuffer;
  }

  return Buffer.from(imagePart.inlineData.data, "base64");
}

// ---------- 4. Save image to repo + get public URL ----------

async function saveImageAndGetUrl(imageBuffer) {
  const filename = `post-${Date.now()}.png`;
  const relDir = "generated-images";
  const absDir = path.join(ROOT, relDir);
  await fs.mkdir(absDir, { recursive: true });
  const absPath = path.join(absDir, filename);
  await fs.writeFile(absPath, imageBuffer);

  execSync(`git config user.name "recess-rejects-bot"`, { cwd: ROOT });
  execSync(`git config user.email "bot@recessrejects.local"`, { cwd: ROOT });
  execSync(`git add ${relDir}/${filename}`, { cwd: ROOT });
  execSync(`git commit -m "Add generated post image ${filename}"`, { cwd: ROOT });
  execSync(`git pull --rebase --autostash`, { cwd: ROOT });
  execSync(`git push`, { cwd: ROOT });

  return `https://raw.githubusercontent.com/${GITHUB_REPOSITORY}/${GITHUB_REF_NAME}/${relDir}/${filename}`;
}

// ---------- 5. Push draft to Buffer ----------

async function createBufferDraft({ caption, hashtags, imageUrl }) {
  const text = `${caption}\n\n${hashtags.join(" ")}`;

  const query = `
    mutation CreateDraftPost($input: CreatePostInput!) {
      createPost(input: $input) {
        ... on PostActionSuccess {
          post { id text status }
        }
        ... on MutationError {
          message
        }
      }
    }
  `;

  const variables = {
    input: {
      text,
      channelId: BUFFER_CHANNEL_ID,
      schedulingType: "automatic",
      mode: "addToQueue",
      saveToDraft: true,
      assets: [{ image: { url: imageUrl } }],
      metadata: {
        instagram: { type: "post", shouldShareToFeed: true },
      },
    },
  };

  const res = await fetch("https://api.buffer.com", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${BUFFER_API_KEY}`,
    },
    body: JSON.stringify({ query, variables }),
  });

  const data = await res.json();
  const result = data?.data?.createPost;

  if (!result || result.message) {
    throw new Error(`Buffer draft creation failed: ${JSON.stringify(data)}`);
  }

  console.log(`✅ Draft created in Buffer: post id ${result.post.id}, status ${result.post.status}`);
}

// ---------- Main ----------

async function main() {
  const brand = await loadJson("config/brand.json");
  const { theme, source } = await pickTheme();
  console.log(`Theme (${source}): ${theme}`);

  const { caption, hashtags, imagePrompt } = await generateCaption(brand, theme);
  console.log(`Caption: ${caption}`);
  console.log(`Hashtags: ${hashtags.join(" ")}`);
  console.log(`Image prompt: ${imagePrompt}`);

  const imageBuffer = await generateImage(brand, imagePrompt);
  console.log("Base scene generated, running tongue-fix pass...");
  const logoBuffer = await fs.readFile(path.join(ROOT, "assets", "NoWordsLogo.png"));
  const fixedImageBuffer = await fixTongue(imageBuffer, logoBuffer);
  const imageUrl = await saveImageAndGetUrl(fixedImageBuffer);
  console.log(`Image URL: ${imageUrl}`);

  await createBufferDraft({ caption, hashtags, imageUrl });
}

main().catch((err) => {
  console.error("❌ Agent run failed:", err);
  process.exit(1);
});
