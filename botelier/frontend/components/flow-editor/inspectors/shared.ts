import type { SlotType } from "../store";

export const slotTypes: { value: SlotType; label: string }[] = [
  { value: "text", label: "Text" },
  { value: "date", label: "Date" },
  { value: "number", label: "Number" },
  { value: "phone", label: "Phone Number" },
  { value: "email", label: "Email" },
  { value: "time", label: "Time" },
  { value: "choice", label: "Choice (Select)" },
];

export const operators = [
  { value: "equals", label: "Equals" },
  { value: "not_equals", label: "Not Equals" },
  { value: "contains", label: "Contains" },
  { value: "greater_than", label: "Greater Than" },
  { value: "less_than", label: "Less Than" },
  { value: "is_empty", label: "Is Empty" },
  { value: "is_not_empty", label: "Has Value" },
];

export const defaultPromptsByType: Record<SlotType, string> = {
  text: "",
  date: "",
  number: "",
  phone: "",
  email: "",
  time: "",
  choice: "",
};

export const defaultRetryByType: Record<SlotType, string> = {
  text: "",
  date: "",
  number: "",
  phone: "",
  email: "",
  time: "",
  choice: "",
};
