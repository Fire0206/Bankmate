import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./index.css";
import "./figma-theme.css";
import "./phase3-compat.css";

const showcaseRoute = lazy(() => import("./showcase/Showcase"));
const currentPath = window.location.pathname.replace(/\/+$/, "") || "/";
const entry =
  currentPath === "/showcase" ? (
    <Suspense fallback={<p role="status">正在读取场景工作台…</p>}>
      {React.createElement(showcaseRoute)}
    </Suspense>
  ) : (
    <App />
  );

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{entry}</React.StrictMode>,
);
