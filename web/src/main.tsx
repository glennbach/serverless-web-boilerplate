import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { boot } from "./boot.ts";

const root = createRoot(document.getElementById("root")!);

function show(content: ReactNode) {
  root.render(
    <StrictMode>
      <main>
        <h1>Proof</h1>
        {content}
      </main>
    </StrictMode>,
  );
}

show(<p>Loading…</p>);

// Boot runs once, outside any component, so StrictMode cannot run the
// sign-in code exchange twice.
boot({
  href: location.href,
  store: sessionStorage,
  now: Date.now(),
  fetchFn: fetch.bind(window),
  replaceUrl: (path) => history.replaceState(null, "", path),
  assign: (url) => location.assign(url),
}).then(
  (email) => {
    if (email !== null) show(<p id="email">{email}</p>);
  },
  (err: unknown) => show(<p role="alert">{err instanceof Error ? err.message : String(err)}</p>),
);
