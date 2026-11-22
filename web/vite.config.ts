import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// /api goes to the Go server unchanged, so /api/me is the same path locally
// and on API Gateway. `vite preview` uses the same proxy.
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8080" } },
});
