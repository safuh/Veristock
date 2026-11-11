import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [
      react(),
      VitePWA({
        registerType: "autoUpdate",
        includeAssets: ["veristock-icon.svg"],
        manifest: {
          id: "/",
          name: "Veristock One",
          short_name: "Veristock",
          description: "Inventory intelligence and stocktaking workspace.",
          start_url: "/",
          scope: "/",
          display: "standalone",
          background_color: "#f5f7fa",
          theme_color: "#101c2c",
          icons: [
            {
              src: "/veristock-icon.svg",
              sizes: "any",
              type: "image/svg+xml",
              purpose: "any maskable"
            }
          ]
        },
        workbox: {
          globPatterns: ["**/*.{js,css,html,svg,ico,png,woff2}"],
          navigateFallback: "/index.html",
          navigateFallbackDenylist: [/^\/api\//],
          cleanupOutdatedCaches: true,
          clientsClaim: true
        },
        devOptions: { enabled: false }
      })
    ],
    server: {
      proxy: {
        "/api": {
          target: env.VERISTOCK_API_URL || "http://127.0.0.1:8000",
          changeOrigin: true
        }
      }
    }
  };
});
