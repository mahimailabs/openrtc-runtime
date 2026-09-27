// @ts-check
// docs.openrtc.tech: a static site. The pages render the MDX files in the repository's docs/, so
// the text has one source and a docs change is a normal PR. Theme pieces shared with the landing
// page live in ../shared.
import { defineConfig } from 'astro/config';
import mdx from '@astrojs/mdx';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  site: 'https://docs.openrtc.tech',
  trailingSlash: 'always',
  // Keep source whitespace: compression drops the space between a line of text and a link that
  // starts the next line.
  compressHTML: false,
  integrations: [mdx()],
  markdown: {
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
      defaultColor: false,
    },
  },
  vite: {
    // The MDX pages (../../docs) and the shared theme (../shared) live outside the site root.
    server: { fs: { allow: [fileURLToPath(new URL('../..', import.meta.url))] } },
  },
});
