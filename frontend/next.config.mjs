/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: "standalone", // small production image, see frontend/Dockerfile
  devIndicators: false,
  async redirects() {
    // Pages that moved into Settings.
    return [
      { source: "/documents", destination: "/settings/files", permanent: false },
      { source: "/keys", destination: "/settings/api", permanent: false },
      { source: "/analytics", destination: "/settings/analytics", permanent: false },
      { source: "/admin/:page(users|audit|policy|models)", destination: "/settings/:page", permanent: false },
    ];
  },
};

export default nextConfig;
