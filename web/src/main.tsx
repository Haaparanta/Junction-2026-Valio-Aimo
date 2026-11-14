import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ui } from "./voice/store";
import "./styles.css";

// Dev builds only: lets QA put the UI into any state from the console (window.__ui.set({...})).
if (import.meta.env.DEV) (window as unknown as { __ui: typeof ui }).__ui = ui;

const root = document.getElementById("root");
if (root) createRoot(root).render(<StrictMode><App /></StrictMode>);
