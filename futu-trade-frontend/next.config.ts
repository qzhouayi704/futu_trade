import type { NextConfig } from "next";

const FLASK_API_URL = process.env.FLASK_API_URL || "http://127.0.0.1:5001";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",

  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${FLASK_API_URL}/api/:path*`,
      },
    ];
  },

  images: {
    formats: ["image/avif", "image/webp"],
  },

  modularizeImports: {
    "lucide-react": {
      transform: "lucide-react/dist/esm/icons/{{kebabCase member}}",
    },
  },
};

export default nextConfig;
