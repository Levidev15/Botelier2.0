# Botelier Docs Site

This is the standalone documentation site for the Botelier platform, built with [Docusaurus 3](https://docusaurus.io/).

It serves as the single source of truth for operator guides, admin guides, KB articles, and API reference. It deploys independently from the main application (e.g. `docs.botelier.com`).

---

## Run Locally

```bash
cd docs-site
npm install
npm run start        # starts dev server on http://localhost:3003
```

The dev server hot-reloads on any markdown or config change.

---

## Build for Production

```bash
cd docs-site
npm run build        # outputs to docs-site/build/
npm run serve        # preview the production build locally
```

---

## Add a Guide

1. Drop a `.md` file into the appropriate section folder under `docs/`:

   | Section | Folder |
   |---|---|
   | Getting Started | `docs/getting-started/` |
   | Assistants | `docs/assistants/` |
   | Flows | `docs/flows/` |
   | Knowledge Bases | `docs/knowledge-bases/` |
   | Tools | `docs/tools/` |
   | Phone Numbers | `docs/phone-numbers/` |
   | SMS & Messaging | `docs/sms/` |
   | SMS Compliance | `docs/sms-compliance/` |
   | Integrations | `docs/integrations/` |
   | Analytics | `docs/analytics/` |
   | Usage & Billing | `docs/usage-billing/` |
   | Team & Access | `docs/team/` |
   | Account Settings | `docs/settings/` |
   | Admin Guide | `docs/admin/` |

2. Add a front matter block at the top of the file:

   ```markdown
   ---
   id: my-page-id
   title: My Page Title
   sidebar_label: Short Sidebar Label
   ---
   ```

3. Add the page ID to `sidebars.js` under the correct category's `items` array.

4. The page is automatically indexed for full-text search.

---

## Update the API Spec URL

The API Reference section renders the FastAPI OpenAPI spec at runtime. The spec URL is controlled by the `DOCS_API_BASE_URL` environment variable (falls back to `http://localhost:8000`):

```bash
# .env or environment variable
DOCS_API_BASE_URL=https://api.botelier.com
```

Alternatively, set `NEXT_PUBLIC_API_URL` if you already use that variable in your deployment.

The spec is fetched from `{DOCS_API_BASE_URL}/api/openapi.json` — this is the FastAPI auto-generated OpenAPI JSON endpoint.

---

## Docusaurus Config

- `docusaurus.config.js` — main configuration (title, navbar, footer, plugins)
- `sidebars.js` — sidebar hierarchy for all doc sections
- `src/css/custom.css` — Botelier brand colors and theme overrides

## Replit Workflow

The `botelier-docs` workflow runs:
```
npm run start --prefix docs-site -- --port 3003
```

This starts the dev server on port 3003, avoiding collisions with the Next.js frontend (3000), the FastAPI backend (3001), and the test MCP server (3002).
