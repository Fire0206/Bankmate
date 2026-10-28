import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";
const root = ReactDOM.createRoot(document.getElementById("root")!);

async function mountApplication() {
  if (currentPath === "/showcase") {
    await import("./showcase/legacy/index.css");
    await import("./showcase/legacy/figma-theme.css");
    await import("./showcase/legacy/phase3-compat.css");
    await import("./showcase/legacy/finance-authority.css");
    const { default: Showcase } = await import("./showcase/Showcase");
    root.render(
      <React.StrictMode>
        <Showcase />
      </React.StrictMode>,
    );
    return;
  }

  await import("./styles/app.css");
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

void mountApplication();
