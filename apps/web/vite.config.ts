import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "FINORCH_");
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        "/api": env.FINORCH_API_TARGET ?? "http://127.0.0.1:8000",
      },
    },
  };
});
