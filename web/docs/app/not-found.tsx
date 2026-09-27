import Link from 'next/link';

export default function NotFound() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-medium">Page not found</h1>
      <p className="text-fd-muted-foreground">The docs are five pages; this is not one of them.</p>
      <Link className="text-fd-primary underline" href="/">
        Back to the docs
      </Link>
    </main>
  );
}
