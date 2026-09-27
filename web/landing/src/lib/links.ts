// Every destination the landing page links to, in one place.
export const REPO = 'https://github.com/mahimailabs/openrtc-runtime';
export const PYPI = 'https://pypi.org/project/openrtc/';
export const DOCS = 'https://docs.openrtc.tech';

/** The repository's star count, read from GitHub at build time. null when GitHub is unreachable. */
export async function fetchStars(): Promise<number | null> {
  try {
    const res = await fetch('https://api.github.com/repos/mahimailabs/openrtc-runtime', {
      headers: { accept: 'application/vnd.github+json' },
      signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return null;
    const { stargazers_count } = (await res.json()) as { stargazers_count?: number };
    return typeof stargazers_count === 'number' ? stargazers_count : null;
  } catch {
    return null;
  }
}
