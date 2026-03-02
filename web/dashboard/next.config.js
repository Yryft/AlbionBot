/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: false,
  },
  typescript: {
    ignoreBuildErrors: true,
  },
};

module.exports = nextConfig;
