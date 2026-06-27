import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { StudioPrototype } from "./prototype/StudioPrototype";

const showStudioPrototype = new URLSearchParams(window.location.search).get("prototype") === "studio";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {showStudioPrototype ? <StudioPrototype /> : <App />}
  </React.StrictMode>
);
