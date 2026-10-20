import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig(function (_a) {
    var mode = _a.mode;
    var env = loadEnv(mode, ".", "VITE_");
    var apiTarget = process.env.VITE_API_TARGET || env.VITE_API_TARGET || "http://127.0.0.1:8000";
    return {
        plugins: [react()],
        server: {
            port: 5173,
            proxy: { "/api": apiTarget, "/health": apiTarget }
        }
    };
});
