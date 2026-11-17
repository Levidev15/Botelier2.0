import { DefaultSession, DefaultUser } from "next-auth";

declare module "next-auth" {
  interface Session {
    accessToken?: string;
    user: {
      id: string;
      replitId: string;
    } & DefaultSession["user"];
  }

  interface User extends DefaultUser {
    replitId: string;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    replitId?: string;
  }
}

export interface UserPermissions {
  assistants: {
    view: boolean;
    create: boolean;
    edit: boolean;
    delete: boolean;
    publish: boolean;
  };
  phone_numbers: {
    view: boolean;
    purchase: boolean;
    configure: boolean;
    release: boolean;
  };
  call_logs: {
    view: boolean;
    view_transcripts: boolean;
    export: boolean;
    edit: boolean;
    delete: boolean;
  };
  knowledge_base: {
    view: boolean;
    create: boolean;
    edit: boolean;
    delete: boolean;
    import: boolean;
  };
  tools: {
    view: boolean;
    create: boolean;
    edit: boolean;
    delete: boolean;
  };
  flows: {
    view: boolean;
    edit: boolean;
    publish: boolean;
    revert: boolean;
  };
  team: {
    view: boolean;
    invite: boolean;
    manage_roles: boolean;
    remove: boolean;
  };
  settings: {
    view: boolean;
    edit: boolean;
    billing: boolean;
    api_keys: boolean;
  };
  integrations: {
    view: boolean;
    manage: boolean;
  };
  usage: {
    view: boolean;
    export: boolean;
  };
  records: {
    view: boolean;
    create: boolean;
    edit: boolean;
    delete: boolean;
    export: boolean;
    manage_types: boolean;
  };
}

export interface UserRole {
  id: string;
  name: string;
  slug: string;
  permissions: UserPermissions;
}

export interface CurrentUser {
  id: string;
  replitId: string;
  email: string | null;
  firstName: string | null;
  lastName: string | null;
  profileImageUrl: string | null;
  userType: "platform_admin" | "account_user";
  isPlatformAdmin: boolean;
  currentAccount: {
    id: string;
    name: string;
    slug: string;
  } | null;
  role: UserRole | null;
  permissions: UserPermissions | null;
}
