import { Link } from "react-router";

import type { Route } from "./+types/home";
import { DEMO_DEFINITIONS } from "~/lib/demo-config";

export function meta({}: Route.MetaArgs) {
  return [
    { title: "OpenRTC Frontend Demo" },
    {
      name: "description",
      content: "Simple dentist and restaurant frontend demo for OpenRTC agent dispatch.",
    },
  ];
}

export default function Home() {
  const demos = Object.values(DEMO_DEFINITIONS);

  return (
    <main className="landing-shell">
      <section className="landing-panel">
        <p className="eyebrow">OpenRTC example frontend</p>
        <h1>Pick a demo and start the matching agent.</h1>
        <p className="landing-copy">
          Both experiences talk to the same worker. The only difference is the
          agent value sent in room metadata when the call begins.
        </p>

        <div className="card-grid">
          {demos.map((demo) => (
            <article className={`demo-card ${demo.accentClassName}`} key={demo.slug}>
              <p className="card-label">{demo.slug}</p>
              <h2>{demo.title}</h2>
              <p>{demo.tagline}</p>
              <p className="card-note">Dispatch target: {demo.agent}</p>
              <Link className="card-link" to={`/${demo.slug}`}>
                Open {demo.title}
              </Link>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
