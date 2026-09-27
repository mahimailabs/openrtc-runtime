// The OpenRTC mark: a worker ring with one live arc, and a voice level inside. It reads as the O
// of OpenRTC. Same drawing as web/shared/Mark.astro, which the landing page uses.
export function Mark() {
  return (
    <svg className="mark" viewBox="0 0 24 24" aria-hidden="true">
      <circle className="mark__ring" cx="12" cy="12" r="9.2" />
      <path className="mark__arc" d="M12 2.8A9.2 9.2 0 0 1 20.4 8.2" />
      <rect className="mark__bar" x="8" y="10" width="1.8" height="4" rx="0.9" />
      <rect className="mark__bar mark__bar--live" x="11.1" y="8" width="1.8" height="8" rx="0.9" />
      <rect className="mark__bar" x="14.2" y="9.5" width="1.8" height="5" rx="0.9" />
    </svg>
  );
}
