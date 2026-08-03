/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow Docker host networking for HMR in development
  allowedDevOrigins: ["localhost:3001", "127.0.0.1:3001"],
};

module.exports = nextConfig;
