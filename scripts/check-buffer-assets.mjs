#!/usr/bin/env node
/**
 * Buffer asset health check
 *
 * Buffer's Instagram integration occasionally attaches a second, corrupt
 * zero-dimension (0x0) image asset alongside the real one on a post — when
 * Instagram's publish step picks the broken asset instead, the live post
 * ships with no visible image. This has been observed on sent posts even
 * though the source image fetch itself succeeded with no error recorded.
 *
 * This script pulls the most recently *sent* posts on the configured
 * channel and flags any with a zero-dimension image asset, so it can be
 * caught by a scheduled check instead of by someone noticing a blank post.
 *
 * Required environment variables:
 *   BUFFER_API_KEY      - Buffer personal API key
 *   BUFFER_CHANNEL_ID    - Buffer channel ID to check
 */

const BUFFER_API_KEY = process.env.BUFFER_API_KEY;
const BUFFER_CHANNEL_ID = process.env.BUFFER_CHANNEL_ID;
// Time-based, not count-based: a fixed-size "most recent N" window means a
// post sent outside Buffer's own knowledge (e.g. deleted directly on
// Instagram, so it never gets replaced through Buffer) stays "sent" in
// Buffer's history forever and would re-trigger this check on every run.
const LOOKBACK_HOURS = Number(process.env.BUFFER_CHECK_LOOKBACK_HOURS || 24);

function requireEnv(name, value) {
  if (!value) {
    console.error(`Missing required environment variable: ${name}`);
    process.exit(1);
  }
}

for (const [name, value] of Object.entries({ BUFFER_API_KEY, BUFFER_CHANNEL_ID })) {
  requireEnv(name, value);
}

async function bufferQuery(query, variables = {}) {
  const res = await fetch("https://api.buffer.com", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${BUFFER_API_KEY}`,
    },
    body: JSON.stringify({ query, variables }),
  });

  if (!res.ok) {
    throw new Error(`Buffer API HTTP error: ${res.status} ${await res.text()}`);
  }

  const data = await res.json();
  if (data.errors) {
    throw new Error(`Buffer API error: ${JSON.stringify(data.errors)}`);
  }
  return data.data;
}

async function getOrganizationId() {
  const data = await bufferQuery(`query GetOrg { account { organizations { id } } }`);
  const orgId = data.account?.organizations?.[0]?.id;
  if (!orgId) {
    throw new Error("Could not resolve a Buffer organizationId from account.organizations.");
  }
  return orgId;
}

async function getRecentSentPosts(organizationId) {
  const query = `
    query RecentSentPosts($input: PostsInput!) {
      posts(input: $input) {
        edges {
          node {
            id
            text
            status
            sentAt
            createdAt
            assets {
              type
              ... on ImageAsset {
                image { width height }
              }
            }
          }
        }
      }
    }
  `;
  const variables = {
    input: {
      organizationId,
      filter: { channelIds: [BUFFER_CHANNEL_ID], status: ["sent"] },
      sort: [{ field: "dueAt", direction: "desc" }],
    },
  };
  const data = await bufferQuery(query, variables);
  const edges = data.posts?.edges || [];
  const cutoff = Date.now() - LOOKBACK_HOURS * 60 * 60 * 1000;
  return edges
    .map((e) => e.node)
    .filter((post) => post.sentAt && new Date(post.sentAt).getTime() >= cutoff);
}

function findBrokenImageAssets(post) {
  return (post.assets || []).filter(
    (asset) => asset.type === "image" && asset.image && (asset.image.width === 0 || asset.image.height === 0)
  );
}

async function main() {
  const organizationId = await getOrganizationId();
  const posts = await getRecentSentPosts(organizationId);
  console.log(`Checked ${posts.length} post(s) sent in the last ${LOOKBACK_HOURS}h on channel ${BUFFER_CHANNEL_ID}.`);

  const broken = [];
  for (const post of posts) {
    const badAssets = findBrokenImageAssets(post);
    if (badAssets.length > 0) {
      broken.push({
        id: post.id,
        sentAt: post.sentAt,
        textPreview: (post.text || "").slice(0, 80),
        badAssetCount: badAssets.length,
        totalAssetCount: (post.assets || []).length,
      });
    }
  }

  if (broken.length === 0) {
    console.log("No zero-dimension image assets found among recent sent posts. All clear.");
    return;
  }

  console.error(`Found ${broken.length} sent post(s) with a broken (0x0) image asset:`);
  for (const b of broken) {
    console.error(
      `- ${b.id} (sent ${b.sentAt}): "${b.textPreview}..." — ${b.badAssetCount}/${b.totalAssetCount} asset(s) broken`
    );
  }
  process.exitCode = 1;
}

main().catch((err) => {
  console.error("Buffer asset check failed:", err);
  process.exit(1);
});
