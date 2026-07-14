/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  guidesSidebar: [
    {
      type: 'category',
      label: 'Getting Started',
      collapsed: false,
      items: [
        'getting-started/platform-overview',
        'getting-started/quick-start',
      ],
    },
    {
      type: 'category',
      label: 'Assistants',
      items: [
        'assistants/creating-an-assistant',
        'assistants/acw-and-qa',
        'assistants/greeting-cache',
      ],
    },
    {
      type: 'category',
      label: 'Flows',
      items: [
        'flows/flow-editor-overview',
        'flows/node-reference',
        'flows/flow-versioning',
        'flows/flow-simulation',
      ],
    },
    {
      type: 'category',
      label: 'Knowledge Bases',
      items: [
        'knowledge-bases/managing-knowledge-bases',
      ],
    },
    {
      type: 'category',
      label: 'Tools',
      items: [
        'tools/tools-overview',
        'tools/tool-types',
        'tools/linking-tools-to-assistants',
      ],
    },
    {
      type: 'category',
      label: 'Phone Numbers',
      items: [
        'phone-numbers/provisioning-numbers',
        'phone-numbers/number-types-and-capabilities',
      ],
    },
    {
      type: 'category',
      label: 'SMS & Messaging',
      items: [
        'sms/messaging-inbox',
        'sms/human-takeover',
        'sms/sms-templates',
        'sms/sms-ai-config',
      ],
    },
    {
      type: 'category',
      label: 'SMS Compliance (A2P 10DLC)',
      items: [
        'sms-compliance/a2p-10dlc-overview',
        'sms-compliance/brand-registration',
        'sms-compliance/campaign-registration',
        'sms-compliance/compliance-checklist',
      ],
    },
    {
      type: 'category',
      label: 'Integrations',
      items: [
        'integrations/integrations-overview',
        'integrations/oracle-opera-ohip',
        'integrations/guestcentric-crs',
        'integrations/canonical-domain-schemas',
        'integrations/universal-capability-tools',
        'integrations/mcp-server',
        'integrations/custom-api-via-flow',
        'integrations/adding-a-new-integration',
      ],
    },
    {
      type: 'category',
      label: 'Analytics',
      items: [
        'analytics/call-analytics',
        'analytics/sms-analytics',
        'analytics/call-logs',
      ],
    },
    {
      type: 'category',
      label: 'Usage & Billing',
      items: [
        'usage-billing/usage-summary',
        'usage-billing/billing-alerts',
      ],
    },
    {
      type: 'category',
      label: 'Team & Access',
      items: [
        'team/team-management',
        'team/permissions-reference',
        'team/api-keys',
      ],
    },
    {
      type: 'category',
      label: 'Account Settings',
      items: [
        'settings/account-settings',
      ],
    },
  ],

  adminSidebar: [
    {
      type: 'category',
      label: 'Admin Guide',
      collapsed: false,
      items: [
        'admin/admin-overview',
        'admin/managing-accounts',
        'admin/managing-users',
        'admin/platform-billing',
        'admin/platform-settings',
        'admin/security-log',
      ],
    },
  ],
};

module.exports = sidebars;
