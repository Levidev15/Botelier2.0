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
  text: "May I have your name, please?",
  date: "What date would you prefer?",
  number: "How many would you like?",
  phone: "What's the best phone number to reach you?",
  email: "What's your email address?",
  time: "What time works best for you?",
  choice: "Which option would you prefer?",
};

export const defaultRetryByType: Record<SlotType, string> = {
  text: "I didn't catch that. Could you please repeat?",
  date: "Please provide a valid date, for example, December 15th.",
  number: "Please tell me a number.",
  phone: "Could you please repeat your phone number?",
  email: "Please provide a valid email address.",
  time: "Please provide a valid time, like 3 PM or 15:00.",
  choice: "Please choose one of the available options.",
};
