interface FormSectionProps {
  id?: string;
  title: string;
  description?: string;
  children: React.ReactNode;
}

export default function FormSection({
  id,
  title,
  description,
  children,
}: FormSectionProps) {
  return (
    <div id={id} className="scroll-mt-24">
      <div className="border border-gray-800 rounded-lg bg-[#0f0f0f] p-6">
        <div className="border-b border-gray-800 pb-4 mb-6">
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          {description && (
            <p className="text-sm text-gray-400 mt-1">{description}</p>
          )}
        </div>
        <div className="space-y-6">{children}</div>
      </div>
    </div>
  );
}
