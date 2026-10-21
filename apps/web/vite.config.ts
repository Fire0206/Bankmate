import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { brand, browserTitle } from "./src/brand.ts";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "FINORCH_");
  return {
    plugins: [
      react(),
      tailwindcss(),
      {
        name: "product-document-brand",
        transformIndexHtml(html: string) {
          return html
            .replace("%PRODUCT_TITLE%", browserTitle)
            .replace("%PRODUCT_DESCRIPTION%", brand.description);
        },
      },
    ],
    server: {
      proxy: {
        "/api": env.FINORCH_API_TARGET ?? "http://127.0.0.1:8000",
      },
    },
  };
});
