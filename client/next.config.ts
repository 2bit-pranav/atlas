import type { NextConfig } from "next";

const BACKEND_URL = "http://127.0.0.1:8001";

const nextConfig: NextConfig = {
    /* config options here */
    devIndicators: false,
    async rewrites() {
        return [
            // Route all /api/* endpoints to FastAPI
            {
                source: "/api/:path*",
                destination: `${BACKEND_URL}/api/:path*`,
            },
        ];
    },
};

export default nextConfig;
