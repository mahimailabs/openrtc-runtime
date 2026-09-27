import defaultMdxComponents from 'fumadocs-ui/mdx';
import { Callout } from 'fumadocs-ui/components/callout';
import type { MDXComponents } from 'mdx/types';
import type { ReactNode } from 'react';

// The pages use <Note>, <Tip> and <Warning> (their Mintlify-era names); each is a Callout.
function Note({ children }: { children: ReactNode }) {
  return <Callout type="info">{children}</Callout>;
}
function Tip({ children }: { children: ReactNode }) {
  return <Callout type="idea">{children}</Callout>;
}
function Warning({ children }: { children: ReactNode }) {
  return <Callout type="warn">{children}</Callout>;
}

export function getMDXComponents(components?: MDXComponents) {
  return {
    ...defaultMdxComponents,
    Note,
    Tip,
    Warning,
    ...components,
  } satisfies MDXComponents;
}

export const useMDXComponents = getMDXComponents;

declare global {
  type MDXProvidedComponents = ReturnType<typeof getMDXComponents>;
}
