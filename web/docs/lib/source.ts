import { llms, loader } from 'fumadocs-core/source';
import { defineDocs } from 'fumadocs-mdx/macro';
import { metaSchema, pageSchema } from 'fumadocs-core/source/schema';
import { docsRoute } from './shared';

// The pages are the Markdown files in the repo's docs/ folder, which the release workflow and
// docs/_check_docs.py also read. docs/meta.json orders them; docs/design/ and the audit notes
// beside them are internal and never published.
const docs = defineDocs({
  dir: '../../docs',
  docs: {
    files: ['index.mdx', 'how-it-works.mdx', 'cli.mdx', 'benchmark.mdx', 'changelog.md'],
    schema: pageSchema,
    postprocess: {
      includeProcessedMarkdown: true,
    },
  },
  meta: {
    files: ['meta.json'],
    schema: metaSchema,
  },
});

// See https://fumadocs.dev/docs/headless/source-api for more info
export const source = loader({
  baseUrl: docsRoute,
  source: docs.toFumadocsSource(),
  plugins: [],
});

export const docsLlms = llms(source, {
  renderPage: async (page) => `# ${page.data.title} (${page.url})

${await page.data.getText('processed')}`,
});
