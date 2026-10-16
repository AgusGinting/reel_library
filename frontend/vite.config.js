import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Saat `npm run dev`, permintaan /api dan /media diteruskan ke Flask (library.py).
const FLASK = "http://127.0.0.1:5000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": FLASK, "/media": FLASK },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
