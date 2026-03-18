import { Suspense } from "react";
import ReportContent from "./ReportContent";

export default function CallAnalyticsReportPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-white flex items-center justify-center">
        <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
      </div>
    }>
      <ReportContent />
    </Suspense>
  );
}
