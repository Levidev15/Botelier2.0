import React from 'react';
import ComponentCreator from '@docusaurus/ComponentCreator';

export default [
  {
    path: '/api-reference/',
    component: ComponentCreator('/api-reference/', '716'),
    exact: true
  },
  {
    path: '/search',
    component: ComponentCreator('/search', '822'),
    exact: true
  },
  {
    path: '/',
    component: ComponentCreator('/', '2e1'),
    exact: true
  },
  {
    path: '/',
    component: ComponentCreator('/', 'c16'),
    routes: [
      {
        path: '/',
        component: ComponentCreator('/', '1d4'),
        routes: [
          {
            path: '/',
            component: ComponentCreator('/', 'c50'),
            routes: [
              {
                path: '/admin/admin-overview',
                component: ComponentCreator('/admin/admin-overview', 'bee'),
                exact: true,
                sidebar: "adminSidebar"
              },
              {
                path: '/admin/managing-accounts',
                component: ComponentCreator('/admin/managing-accounts', '64a'),
                exact: true,
                sidebar: "adminSidebar"
              },
              {
                path: '/admin/managing-users',
                component: ComponentCreator('/admin/managing-users', '09e'),
                exact: true,
                sidebar: "adminSidebar"
              },
              {
                path: '/admin/platform-billing',
                component: ComponentCreator('/admin/platform-billing', 'a98'),
                exact: true,
                sidebar: "adminSidebar"
              },
              {
                path: '/admin/platform-settings',
                component: ComponentCreator('/admin/platform-settings', 'cee'),
                exact: true,
                sidebar: "adminSidebar"
              },
              {
                path: '/admin/security-log',
                component: ComponentCreator('/admin/security-log', 'd9e'),
                exact: true,
                sidebar: "adminSidebar"
              },
              {
                path: '/analytics/call-analytics',
                component: ComponentCreator('/analytics/call-analytics', '7a1'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/analytics/call-logs',
                component: ComponentCreator('/analytics/call-logs', 'b29'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/analytics/sms-analytics',
                component: ComponentCreator('/analytics/sms-analytics', '43e'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/assistants/acw-and-qa',
                component: ComponentCreator('/assistants/acw-and-qa', 'c0f'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/assistants/creating-an-assistant',
                component: ComponentCreator('/assistants/creating-an-assistant', '57f'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/assistants/greeting-cache',
                component: ComponentCreator('/assistants/greeting-cache', '9c4'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/flows/flow-editor-overview',
                component: ComponentCreator('/flows/flow-editor-overview', '935'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/flows/flow-simulation',
                component: ComponentCreator('/flows/flow-simulation', 'c59'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/flows/flow-versioning',
                component: ComponentCreator('/flows/flow-versioning', '35d'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/flows/node-reference',
                component: ComponentCreator('/flows/node-reference', 'ee3'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/getting-started/platform-overview',
                component: ComponentCreator('/getting-started/platform-overview', '53c'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/getting-started/quick-start',
                component: ComponentCreator('/getting-started/quick-start', '0e3'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/integrations/custom-api-via-flow',
                component: ComponentCreator('/integrations/custom-api-via-flow', '8de'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/integrations/guestcentric-crs',
                component: ComponentCreator('/integrations/guestcentric-crs', 'b6c'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/integrations/integrations-overview',
                component: ComponentCreator('/integrations/integrations-overview', '79d'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/integrations/mcp-server',
                component: ComponentCreator('/integrations/mcp-server', '748'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/integrations/oracle-opera-ohip',
                component: ComponentCreator('/integrations/oracle-opera-ohip', '4ba'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/knowledge-bases/managing-knowledge-bases',
                component: ComponentCreator('/knowledge-bases/managing-knowledge-bases', '270'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/phone-numbers/number-types-and-capabilities',
                component: ComponentCreator('/phone-numbers/number-types-and-capabilities', '57a'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/phone-numbers/provisioning-numbers',
                component: ComponentCreator('/phone-numbers/provisioning-numbers', 'd48'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/settings/account-settings',
                component: ComponentCreator('/settings/account-settings', '060'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms-compliance/a2p-10dlc-overview',
                component: ComponentCreator('/sms-compliance/a2p-10dlc-overview', 'f76'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms-compliance/brand-registration',
                component: ComponentCreator('/sms-compliance/brand-registration', 'b3d'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms-compliance/campaign-registration',
                component: ComponentCreator('/sms-compliance/campaign-registration', '49e'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms-compliance/compliance-checklist',
                component: ComponentCreator('/sms-compliance/compliance-checklist', '1b4'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms/human-takeover',
                component: ComponentCreator('/sms/human-takeover', '2c2'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms/messaging-inbox',
                component: ComponentCreator('/sms/messaging-inbox', '734'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms/sms-ai-config',
                component: ComponentCreator('/sms/sms-ai-config', '48e'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/sms/sms-templates',
                component: ComponentCreator('/sms/sms-templates', 'beb'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/team/api-keys',
                component: ComponentCreator('/team/api-keys', '276'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/team/permissions-reference',
                component: ComponentCreator('/team/permissions-reference', '559'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/team/team-management',
                component: ComponentCreator('/team/team-management', '928'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/tools/linking-tools-to-assistants',
                component: ComponentCreator('/tools/linking-tools-to-assistants', 'fc0'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/tools/tool-types',
                component: ComponentCreator('/tools/tool-types', 'e4c'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/tools/tools-overview',
                component: ComponentCreator('/tools/tools-overview', '6f3'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/usage-billing/billing-alerts',
                component: ComponentCreator('/usage-billing/billing-alerts', '1ec'),
                exact: true,
                sidebar: "guidesSidebar"
              },
              {
                path: '/usage-billing/usage-summary',
                component: ComponentCreator('/usage-billing/usage-summary', '524'),
                exact: true,
                sidebar: "guidesSidebar"
              }
            ]
          }
        ]
      }
    ]
  },
  {
    path: '*',
    component: ComponentCreator('*'),
  },
];
