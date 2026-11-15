import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the backend runs separately on port 8077. Proxying /api to it
// lets the page use the same relative URLs as in production, where the backend
// serves the built page itself (see backend/hipparchus/serve.py).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": { target: "http://127.0.0.1:8077", rewrite: (p) => p.replace(/^\/api/, "") },
    },
  },
});
