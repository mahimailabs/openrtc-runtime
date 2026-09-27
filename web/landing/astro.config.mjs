// @ts-check
// openrtc.tech: the landing page, a static site. The theme it shares with the docs lives in
// ../shared; the docs themselves are docs.openrtc.tech (../docs).
import { defineConfig } from 'astro/config';
import { fileURLToPath } from 'node:url';

export default defineConfig({
  site: 'https://openrtc.tech',
  trailingSlash: 'always',
  compressHTML: false,
  markdown: {
    shikiConfig: {
      themes: { light: 'github-light', dark: 'github-dark' },
      defaultColor: false,
    },
  },
  vite: {
    // The shared theme (../shared) lives outside the site root.
    server: { fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] } },
  },
});
