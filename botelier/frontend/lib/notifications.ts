import { toast } from "sonner";

export const notify = {
  success: (message: string) => {
    toast.success(message);
  },

  error: (message: string) => {
    toast.error(message);
  },

  info: (message: string) => {
    toast.info(message);
  },

  warning: (message: string) => {
    toast(message, {
      style: { background: "#78350f", color: "#fde68a", border: "1px solid #92400e" },
    });
  },

  loading: (message: string) => {
    return toast.loading(message);
  },

  promise: <T,>(
    promise: Promise<T>,
    messages: {
      loading: string;
      success: string | ((data: T) => string);
      error: string | ((error: any) => string);
    }
  ) => {
    return toast.promise(promise, messages);
  },

  dismiss: (toastId?: string | number) => {
    toast.dismiss(toastId);
  },
};

export async function confirmAction(
  message: string,
  options?: {
    confirmText?: string;
    cancelText?: string;
  }
): Promise<boolean> {
  return new Promise((resolve) => {
    toast(message, {
      action: {
        label: options?.confirmText || "Confirm",
        onClick: () => resolve(true),
      },
      cancel: {
        label: options?.cancelText || "Cancel",
        onClick: () => resolve(false),
      },
      duration: Infinity,
    });
  });
}
