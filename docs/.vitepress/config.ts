import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'OpenRTC',
  description: 'Run multiple LiveKit voice agents in a single shared worker process.',
  base: '/openrtc-python/',
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    logo: '/logo.svg',
    nav: [
      { text: 'Guide', link: '/getting-started' },
      { text: 'Concepts', link: '/concepts/architecture' },
      { text: 'API', link: '/api/pool' },
      { text: 'Examples', link: '/examples' },
    ],
    sidebar: {
      '/': [
        {
          text: 'Introduction',
          items: [
            { text: 'Overview', link: '/' },
            { text: 'Getting Started', link: '/getting-started' },
          ],
        },
        {
          text: 'Core Concepts',
          items: [
            { text: 'Architecture', link: '/concepts/architecture' },
          ],
        },
        {
          text: 'Reference',
          items: [
            { text: 'AgentPool API', link: '/api/pool' },
            { text: 'CLI', link: '/cli' },
            { text: 'Examples', link: '/examples' },
            { text: 'GitHub Pages Deployment', link: '/deployment/github-pages' },
          ],
        },
      ],
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/mahimailabs/openrtc' },
    ],
    editLink: {
      pattern: 'https://github.com/mahimailabs/openrtc/edit/main/docs/:path',
      text: 'Edit this page on GitHub',
    },
    search: {
      provider: 'local',
    },
    footer: {
      message: 'Released under the MIT License.',
      copyright: 'Copyright © Mahimai Raja J',
    },
  },
})
