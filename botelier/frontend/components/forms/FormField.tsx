interface FormFieldProps {
  label: string;
  description?: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}

export default function FormField({
  label,
  description,
  required = false,
  error,
  children,
}: FormFieldProps) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-200 mb-2">
        {label}
        {required && <span className="text-red-500 ml-1">*</span>}
      </label>
      {description && (
        <p className="text-xs text-gray-500 mb-2">{description}</p>
      )}
      {children}
      {error && <p className="text-xs text-red-500 mt-2">{error}</p>}
    </div>
  );
}
