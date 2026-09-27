import { fileURLToPath } from 'node:url';
import { createMDX } from 'fumadocs-mdx/next';

const withMDX = createMDX();

// A fully static site (out/), served from Cloudflare Workers static assets (wrangler.jsonc).
// trailingSlash keeps the page URLs the Astro site had: /how-it-works/ and so on.
/** @type {import('next').NextConfig} */
const config = {
  output: 'export',
  // The pages live in the repo's docs/ folder, outside this app: let the bundler read them.
  turbopack: { root: fileURLToPath(new URL('../..', import.meta.url)) },
  trailingSlash: true,
  reactStrictMode: true,
  images: { unoptimized: true },
};

export default withMDX(config);
