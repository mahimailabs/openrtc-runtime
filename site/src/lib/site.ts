// The five pages, in reading order. The header, the pager and the docs check read this list.
export const REPO = 'https://github.com/mahimailabs/openrtc-runtime';
export const PYPI = 'https://pypi.org/project/openrtc/';

export interface Page {
  href: string;
  label: string;
  /** The MDX file under ../docs that holds the text. */
  file: string;
}

export const PAGES: Page[] = [
  { href: '/', label: 'Why OpenRTC', file: 'index.mdx' },
  { href: '/how-it-works/', label: 'How it works', file: 'how-it-works.mdx' },
  { href: '/cli/', label: 'CLI', file: 'cli.mdx' },
  { href: '/benchmark/', label: 'Benchmark', file: 'benchmark.mdx' },
  { href: '/changelog/', label: 'Changelog', file: 'changelog.md' },
];
