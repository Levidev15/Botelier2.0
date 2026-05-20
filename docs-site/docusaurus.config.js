// @ts-check

// Patch webpack ProgressPlugin to be compatible with webpackbar (used by Docusaurus)
// and webpack 5.92+ which added strict schema validation that rejects webpackbar's
// extra options (name, color, reporters, reporter).
try {
  const webpack = require('./node_modules/webpack');
  const OriginalProgressPlugin = webpack.ProgressPlugin;
  const VALID_OPTS = new Set([
    'activeModules','dependencies','dependenciesCount','entries',
    'handler','modules','modulesCount','percentBy','profile','progressBar',
  ]);
  function PatchedProgressPlugin(options) {
    let patchedOpts = options;
    if (options && typeof options === 'object' && typeof options !== 'function') {
      patchedOpts = {};
      for (const [k, v] of Object.entries(options)) {
        if (VALID_OPTS.has(k)) patchedOpts[k] = v;
      }
    }
    OriginalProgressPlugin.call(this, patchedOpts);
  }
  PatchedProgressPlugin.prototype = Object.create(OriginalProgressPlugin.prototype);
  PatchedProgressPlugin.prototype.constructor = PatchedProgressPlugin;
  Object.setPrototypeOf(PatchedProgressPlugin, OriginalProgressPlugin);
  webpack.ProgressPlugin = PatchedProgressPlugin;
} catch (_) {}

const { themes: prismThemes } = require('prism-react-renderer');

const DOCS_BASE_URL = process.env.DOCS_BASE_URL || 'http://localhost:3001';
const DOCS_API_BASE_URL = process.env.DOCS_API_BASE_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'Botelier',
  tagline: 'Multichannel AI Platform — Operator & Developer Docs',
  favicon: 'img/favicon.ico',

  url: DOCS_BASE_URL,
  baseUrl: '/',

  onBrokenLinks: 'warn',
  onBrokenMarkdownLinks: 'warn',

  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          sidebarPath: require.resolve('./sidebars.js'),
          routeBasePath: '/',
        },
        blog: false,
        theme: {
          customCss: require.resolve('./src/css/custom.css'),
        },
      }),
    ],
    [
      'redocusaurus',
      {
        specs: [
          {
            // Use live backend spec when DOCS_API_BASE_URL is set;
            // fall back to the committed placeholder spec for local builds
            // and CI where the backend isn't running.
            spec: DOCS_API_BASE_URL !== 'http://localhost:8000'
              ? `${DOCS_API_BASE_URL}/api/openapi.json`
              : './static/openapi.json',
            route: '/api-reference/',
          },
        ],
        theme: {
          primaryColor: '#3b82f6',
          options: {
            disableSearch: false,
            hideDownloadButton: false,
          },
        },
      },
    ],
  ],

  plugins: [
    [
      '@easyops-cn/docusaurus-search-local',
      {
        hashed: true,
        indexBlog: false,
        docsRouteBasePath: '/',
        searchBarPosition: 'right',
      },
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        defaultMode: 'dark',
        disableSwitch: false,
        respectPrefersColorScheme: false,
      },
      navbar: {
        title: 'Botelier',
        logo: {
          alt: 'Botelier',
          src: 'img/logo.svg',
          srcDark: 'img/logo.svg',
        },
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'guidesSidebar',
            position: 'left',
            label: 'Guides',
          },
          {
            type: 'docSidebar',
            sidebarId: 'adminSidebar',
            position: 'left',
            label: 'Admin',
          },
          {
            to: '/api-reference',
            label: 'API Reference',
            position: 'left',
          },
          {
            href: 'https://github.com/botelier',
            label: 'GitHub',
            position: 'right',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              { label: 'Getting Started', to: '/getting-started/platform-overview' },
              { label: 'Assistants', to: '/assistants/creating-an-assistant' },
              { label: 'Flows', to: '/flows/flow-editor-overview' },
            ],
          },
          {
            title: 'Platform',
            items: [
              { label: 'Admin Guide', to: '/admin/admin-overview' },
              { label: 'API Reference', to: '/api-reference' },
              { label: 'Usage & Billing', to: '/usage-billing/usage-summary' },
            ],
          },
        ],
        copyright: `Copyright © ${new Date().getFullYear()} Botelier. Built with Docusaurus.`,
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        additionalLanguages: ['json', 'bash', 'python', 'typescript'],
      },
    }),
};

module.exports = config;
