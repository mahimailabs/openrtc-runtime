import { createGetUrl } from 'fumadocs-core/source';

// docs.openrtc.tech serves the docs at the root, so the page URLs stay /how-it-works/ and so on.
export const appName = 'OpenRTC';
export const siteUrl = 'https://docs.openrtc.tech';
export const docsRoute = '/';
export const docsImageRoute = '/og';
export const docsContentRoute = '/llms.mdx';
export const pypiUrl = 'https://pypi.org/project/openrtc/';

export const gitConfig = {
  user: 'mahimailabs',
  repo: 'openrtc-runtime',
  branch: 'main',
  /** Where the page files live in the repo. */
  contentDir: 'docs',
};

const getContentUrl = createGetUrl(docsContentRoute);

/** The page as plain Markdown, for AI agents: /llms.mdx/how-it-works/content.md. */
export function getPageMarkdownUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'content.md'];

  return { segments, url: getContentUrl(segments, page.locale) };
}

const getImageUrl = createGetUrl(docsImageRoute);

export function getPageImageUrl(page: { slugs: string[]; locale?: string }) {
  const segments = [...page.slugs, 'image.png'];

  return { segments, url: getImageUrl(segments, page.locale) };
}
