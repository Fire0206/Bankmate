import React from "react";
import ReactDOM from "react-dom/client";

import App from "./App";
import "./index.css";
import Showcase from "./showcase/Showcase";

const entry = window.location.pathname === "/showcase" ? <Showcase /> : <App />;

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>{entry}</React.StrictMode>,
);
