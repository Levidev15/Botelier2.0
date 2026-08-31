/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  allowedDevOrigins: ["*.riker.replit.dev", "*.replit.dev", "127.0.0.1"],

  webpack: (config, { isServer }) => {
    if (isServer) {
      // Next.js 14.2.x dev server bug: the webpack-runtime.js for complex pages
      // (1000+ modules) references ./vendor-chunks/@babel.js but the file is never
      // written to disk, causing a MODULE_NOT_FOUND 500 on every page load.
      // Marking @babel/runtime as a Node.js external bypasses vendor-chunk creation
      // entirely — webpack emits require('@babel/runtime/...') which Node resolves
      // directly from node_modules without any missing intermediate file.
      const prev = config.externals ?? [];
      const prevList = Array.isArray(prev) ? prev : [prev];
      config.externals = [
        ...prevList,
        function babelRuntimeExternal({ request }, callback) {
          if (request && request.startsWith("@babel/runtime")) {
            return callback(null, "commonjs " + request);
          }
          callback();
        },
      ];
    }
    return config;
  },
};

export default nextConfig;
