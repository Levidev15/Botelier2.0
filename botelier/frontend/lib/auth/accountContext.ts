const isBrowser = typeof window !== "undefined";

export interface AccountContext {
  accountId: string;
  accountName: string;
  accountSlug: string;
  sessionToken?: string;
  sessionExpires?: string;
  isAdminSession: boolean;
}

const STORAGE_KEY = "botelier_account_context";

export function setAccountContext(context: AccountContext): void {
  if (!isBrowser) return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(context));
  } catch {
    // Ignore storage errors
  }
}

export function getAccountContext(): AccountContext | null {
  if (!isBrowser) return null;
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) return null;

    const context = JSON.parse(stored) as AccountContext;

    if (context.sessionExpires) {
      const expires = new Date(context.sessionExpires);
      if (expires < new Date()) {
        clearAccountContext();
        return null;
      }
    }

    return context;
  } catch {
    return null;
  }
}

export function clearAccountContext(): void {
  if (!isBrowser) return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}

export function getAccountId(): string | null {
  const context = getAccountContext();
  return context?.accountId || null;
}

export function isAdminViewingAccount(): boolean {
  const context = getAccountContext();
  return context?.isAdminSession === true;
}
