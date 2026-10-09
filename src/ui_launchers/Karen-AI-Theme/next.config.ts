import path from 'path';
import os from 'os';
import fs from 'fs';
import type {NextConfig} from 'next';

const isDocker = process.env.KAREN_DOCKER === 'true' || 
                 process.env.IS_DOCKER === 'true' || 
                 process.env.HOSTNAME?.includes('api') || 
                 process.env.HOSTNAME?.includes('web');

let BACKEND_URL = process.env.KAREN_BACKEND_URL || process.env.BACKEND_URL || '';

if (isDocker) {
    BACKEND_URL = 'http://api:8000';
} else if (!BACKEND_URL) {
    BACKEND_URL = 'http://localhost:8000';
}

const backendBaseUrl = BACKEND_URL.replace(/\/$/, '');

console.log('🚀 Next.js Configuration:');
console.log(`- isDocker: ${isDocker}`);
console.log(`- RESOLVED backendBaseUrl: ${backendBaseUrl}`);

const devOriginCandidates = [
  'localhost',
  '127.0.0.1',
  'api',
  'web',
  'host.docker.internal',
  process.env.HOSTNAME,
  process.env.NEXT_PUBLIC_APP_URL,
  process.env.KAREN_APP_URL,
  process.env.APP_URL,
];

let privateInterfaceHosts: string[] = [];
try {
  privateInterfaceHosts = Object.values(os.networkInterfaces())
    .flat()
    .filter((address): address is NonNullable<typeof address> => Boolean(address))
    .filter((address) => address.family === 'IPv4' && !address.internal)
    .map((address) => address.address);
} catch (error) {
  console.warn('⚠️ [Next.js Configuration] Failed to read network interfaces; continuing without private interface origins.', error);
}

const allowedDevOrigins = Array.from(
  new Set(
    devOriginCandidates
      .filter((value): value is string => Boolean(value))
      .flatMap((value) => {
        try {
          const parsed = new URL(value);
          return [value, parsed.hostname];
        } catch {
          return [value];
        }
      })
      // Allow the actual container / LAN IPv4 hosts that Next may advertise
      // for HMR in development.
      .concat(privateInterfaceHosts),
  ),
);

const nextConfig: NextConfig = {
  /* config options here */
  outputFileTracingRoot: path.resolve(__dirname, '../..'),
  allowedDevOrigins,
  transpilePackages: [
    'rehype-raw', 
    'remark-gfm', 
    'remark-rehype',
    'hast-util-raw', 
    'decode-named-character-reference',
    'unist-util-visit',
    'unist-util-visit-parents',
    'vfile',
    'vfile-message',
    'micromark',
    'micromark-util-symbol',
    'micromark-util-types',
    'mdast-util-from-markdown',
    'mdast-util-to-hast',
    'hast-util-to-html'
  ],

  typescript: {
    ignoreBuildErrors: true,
  },
  eslint: {
    ignoreDuringBuilds: true,
  },
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'placehold.co',
        port: '',
        pathname: '/**',
      },
    ],
  },

  async rewrites() {
    // API proxying is handled by App Router route handlers under src/app/api,
    // including a catch-all proxy route. Rewriting /api/* here can create
    // self-referential loops when BACKEND_URL matches the Next dev origin.
    console.log('📡 [Rewrites] No /api rewrite configured - this is normal when using App Router route handlers');
    return [];
  },

  webpack: (config) => {

    // 1. Set up plugin repo alias for dynamic loading
    if (!config.resolve) config.resolve = {};
    if (!config.resolve.alias) config.resolve.alias = {};

    const pluginsDir = path.resolve(__dirname, 'src/plugin_repo');
    if (fs.existsSync(pluginsDir)) {
      // Plugin repo exists, alias @plugins to it (note: no slash after @)
      config.resolve.alias['@plugins'] = pluginsDir;
      // The webpack hook runs per compiler and rebuild; no per-pass logging.
    } else {
      // Fallback to plugin_host for safe require.context
      config.resolve.alias['@plugins'] = path.resolve(__dirname, 'src/plugin_host');
      // Keep compatibility alias without repeating a rebuild-time warning.
    }

    // 2. Gracefully handle optional legacy plugins that may not be installed.
    //    If the file doesn't exist, we alias the path to false so Webpack 
    //    ignores it instead of throwing a "Module not found" error that stalls the app.
    const legacyDataConnector = path.resolve(__dirname, 'src/plugin_repo/data_connector/ui/DataConnectorPluginPage');
    if (!fs.existsSync(`${legacyDataConnector}.tsx`) && !fs.existsSync(`${legacyDataConnector}.jsx`)) {
      if (!config.resolve) config.resolve = {};
      if (!config.resolve.alias) config.resolve.alias = {};
      config.resolve.alias['@/plugins/data_connector/ui/DataConnectorPluginPage'] = false;
      // Optional plugin absence is represented by the alias, not a warning.
    }

    return config;
  },
};

export default nextConfig;
