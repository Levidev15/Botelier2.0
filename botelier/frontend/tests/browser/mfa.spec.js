const { expect, test } = require("@playwright/test");
const fs = require("node:fs");
const path = require("node:path");

const baseURL = process.env.MFA_BROWSER_BASE_URL || "http://127.0.0.1:5011";
const user = { id: "offline-test-user", email: "security@example.test", user_type: "platform_admin" };
const status = {
  user,
  mfa_enabled: true,
  mfa_required: true,
  enrollment_required: false,
  policy_required: true,
  primary_fresh: true,
  mfa_fresh: false,
  recovery_codes_remaining: 10,
};

test.beforeEach(async ({ page }) => {
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin === baseURL) return route.continue();
    return route.abort("blockedbyclient");
  });
});

async function mockSecurityApi(page) {
  let verified = false;
  const requests = [];
  await page.route("**/api/auth/session", route => route.fulfill({ json: {} }));
  await page.route("**/api/auth/mfa/**", async route => {
    const request = route.request();
    const requestPath = new URL(request.url()).pathname.split("/mfa")[1];
    requests.push({ path: requestPath, method: request.method(), csrf: request.headers()["x-mfa-csrf"] });
    if (requestPath === "/status" || requestPath === "/bootstrap") {
      return route.fulfill({ json: { ...status, mfa_fresh: verified, mfa_required: !verified } });
    }
    if (requestPath === "/verify") {
      verified = true;
      return route.fulfill({ json: { user, access_token: "offline-full-assurance-token", mfa_required: false } });
    }
    return route.fulfill({ status: 404, json: { detail: "Unexpected offline test request" } });
  });
  return requests;
}

test("password login retains no credential until MFA verification succeeds", async ({ page }) => {
  await mockSecurityApi(page);
  await page.route("**/api/auth/login", route => route.fulfill({
    json: { access_token: null, user, mfa_required: true, enrollment_required: false },
  }));
  await page.goto("/login");

  const screenshotPath = path.resolve(process.cwd(), "../../generated-artifacts/offline-login.png");
  fs.mkdirSync(path.dirname(screenshotPath), { recursive: true });
  await page.screenshot({ path: screenshotPath, fullPage: true });

  await page.locator('input[type="email"]').fill(user.email);
  await page.locator('input[type="password"]').fill("offline-test-password");
  await page.getByRole("button", { name: "Sign In", exact: true }).click();
  await expect(page).toHaveURL(/\/security/);
  await expect(page.getByRole("heading", { name: "Verify your authenticator" })).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("botelier_token"))).toBeNull();

  await page.getByLabel("Authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify", exact: true }).click();
  await expect(page.getByText("Authenticator verified.")).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("botelier_token"))).toBe("offline-full-assurance-token");
});

test("Replit security callback uses same-origin POST exchange, never raw identity tokens", async ({ page }) => {
  await mockSecurityApi(page);
  let method = "";
  await page.route("**/api/auth/token", route => {
    method = route.request().method();
    expect(route.request().headers()["x-mfa-csrf"]).toBe("1");
    return route.fulfill({ json: status });
  });

  await page.goto("/security?replit=1");
  await expect(page.getByRole("heading", { name: "Verify your authenticator" })).toBeVisible();
  expect(method).toBe("POST");
  expect(await page.evaluate(() => localStorage.getItem("botelier_token"))).toBeNull();
});
