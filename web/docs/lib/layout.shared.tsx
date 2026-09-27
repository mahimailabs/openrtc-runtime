import type { BaseLayoutProps } from 'fumadocs-ui/layouts/shared';
import { Mark } from '@/components/mark';
import { appName, gitConfig, pypiUrl } from './shared';

export function baseOptions(): BaseLayoutProps {
  return {
    nav: {
      title: (
        <>
          <Mark />
          <span className="font-medium">{appName}</span>
        </>
      ),
      url: '/',
    },
    githubUrl: `https://github.com/${gitConfig.user}/${gitConfig.repo}`,
    links: [{ text: 'PyPI', url: pypiUrl, external: true }],
  };
}
