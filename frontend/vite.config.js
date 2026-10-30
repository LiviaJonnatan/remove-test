import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The app only calls relative /api/... URLs. In the container nginx forwards them to the API
// (nginx.conf); in development Vite's server does the same, so neither build knows the API's address.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  // npm test: the tests render the page in jsdom, a browser simulated in Node, with fetch faked.
  test: { environment: "jsdom" },
});
