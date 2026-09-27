'use client';
import SearchDialog from '@/components/search';
import { RootProvider } from 'fumadocs-ui/provider/next';
import { type ReactNode } from 'react';

// Dark first, like the landing page and the rest of the mahimai.ca family.
export function Provider({ children }: { children: ReactNode }) {
  return (
    <RootProvider search={{ SearchDialog }} theme={{ defaultTheme: 'dark' }}>
      {children}
    </RootProvider>
  );
}
