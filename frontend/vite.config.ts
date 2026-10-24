import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// /api goes to the FastAPI backend (backend/) during development
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8000" } },
});
