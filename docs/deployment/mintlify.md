---
title: Deploying with Mintlify
description: How to connect the OpenRTC docs to Mintlify for hosting and continuous deployment.
icon: cloud-arrow-up
---

# Deploying with Mintlify

OpenRTC docs are built with [Mintlify](https://mintlify.com). The `docs/` directory
contains `mint.json` (navigation and branding) and all content pages as `.md` / `.mdx` files.

## One-time setup

1. Go to [dashboard.mintlify.com](https://dashboard.mintlify.com) and sign in.
2. Click **New Docs** and connect the `mahimailabs/openrtc` GitHub repository.
3. Set the **docs directory** to `docs/`.
4. Mintlify reads `docs/mint.json` as the entry point and syncs all content pages automatically.
5. Confirm the published URL (typically `openrtc.mintlify.app` or a custom domain).

## Continuous deployment

Once connected, every push to the default branch triggers an automatic sync. No GitHub Actions workflow is needed — Mintlify handles the build and deploy pipeline.

To preview changes before merge, Mintlify generates a preview URL for each pull request automatically.

## Custom domain

1. In the Mintlify dashboard, go to **Settings → Custom Domain**.
2. Add your domain (e.g. `docs.openrtc.dev`).
3. Add a CNAME record pointing to `hosting.mintlify.com` at your DNS provider.

## Local preview

Install the Mintlify CLI:

```bash
npm install -g mintlify
```

Then run from the `docs/` directory:

```bash
cd docs
mintlify dev
```

This opens a local preview at `http://localhost:3000`.

## Updating navigation

Edit `docs/mint.json` to add or reorder pages:

```json
{
  "navigation": [
    {
      "tab": "Overview",
      "groups": [
        {
          "group": "Introduction",
          "pages": ["index", "getting-started"]
        }
      ]
    }
  ]
}
```

Changes take effect on the next push (or immediately in local preview).
