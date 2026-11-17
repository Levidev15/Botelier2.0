"use client";

import { useState } from "react";
import type { NativePreviewInput, NativePreviewOutcome, PendingNativePreview } from "./nativePreview";
import { isNativeOutcomeOnly } from "./nativePreview";

interface NativePreviewCardProps {
  pending: PendingNativePreview;
  isLoading: boolean;
  onSubmit: (input: NativePreviewInput) => Promise<void>;
}

export default function NativePreviewCard({ pending, isLoading, onSubmit }: NativePreviewCardProps) {
  const outcomeOnly = isNativeOutcomeOnly(pending.source_kind);
  const [dataJson, setDataJson] = useState("");
  const [statusCode, setStatusCode] = useState("200");
  const [outcome, setOutcome] = useState<NativePreviewOutcome>(outcomeOnly ? "success" : "auto");
  const isMcp = pending.source_kind.startsWith("mcp");
  const expired = pending.expires_in_seconds <= 0;
  const idPrefix = `sample-${pending.request_id}`;
  const outcomeLabel = pending.source_kind === "transfer" ? "Transfer outcome" : "Provider outcome";
  const successLabel = pending.source_kind === "transfer" ? "Success" : "Success / accepted";
  const failureLabel = pending.source_kind === "transfer" ? "Failure" : "Failure / uncertain";
  const sampleInstructions = outcomeOnly
    ? pending.source_kind === "transfer"
      ? "Select a simulated transfer outcome only. No call is moved, and no provider body or caller confirmation is accepted."
      : "Select a simulated provider outcome only. Success produces a canonical accepted receipt; failures remain uncertain. No message body, private URL or provider response is accepted or shown."
    : isMcp
      ? "Paste a synthetic MCP result envelope, including isError, structuredContent or content. Do not run discovery or Test."
      : pending.source_kind === "record"
        ? "Paste sample result data for this simulated Record action. Nothing is written."
        : "Paste parsed API, integration or saved-tool result data before response mapping. Do not contact the API or provider.";

  const changeOutcome = (value: string) => {
    const next = value as NativePreviewOutcome;
    setOutcome(next);
    const currentStatus = Number(statusCode);
    if (next === "success" && (currentStatus < 200 || currentStatus >= 300)) {
      setStatusCode("200");
    } else if (next === "error" && currentStatus >= 200 && currentStatus < 300) {
      setStatusCode("500");
    }
  };

  const changeStatus = (value: string) => {
    setStatusCode(value);
    if (!outcomeOnly || !value) return;
    const status = Number(value);
    setOutcome(status >= 200 && status < 300 ? "success" : "error");
  };

  return (
    <form
      aria-label={outcomeOnly ? "Select simulated action outcome" : "Supply sample action response"}
      className="space-y-3 rounded-lg border border-amber-700/60 bg-amber-950/20 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!isLoading && !expired) void onSubmit({
          requestId: pending.request_id,
          dataJson: outcomeOnly ? "{}" : dataJson,
          statusCode: Number(statusCode),
          outcome,
        });
      }}
    >
      <div>
        <h4 className="text-xs font-semibold text-amber-100">
          {outcomeOnly ? "Waiting for a simulated outcome" : "Waiting for a sample response"}
        </h4>
        <p className="mt-1 break-all text-[11px] text-gray-400">
          Node: <span className="font-mono text-gray-200">{pending.node_id}</span>
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-gray-300">
          {sampleInstructions}
          {" "}
          {outcomeOnly
            ? "Only the selected status/outcome is submitted; nothing is sent, moved, or spoken."
            : "Your configured mapping and cleanup will run. This does not make an external request."}
        </p>
      </div>
      {!outcomeOnly && (
        <div>
          <label htmlFor={`${idPrefix}-json`} className="mb-1 block text-[11px] text-gray-300">
            Sample response JSON
          </label>
          <textarea
            id={`${idPrefix}-json`}
            aria-label="Sample response JSON"
            value={dataJson}
            onChange={(event) => setDataJson(event.target.value)}
            required
            disabled={isLoading || expired}
            spellCheck={false}
            autoComplete="off"
            placeholder={isMcp ? '{"isError":false,"structuredContent":{},"content":[]}' : '{"rooms":[]}'}
            className="min-h-32 w-full resize-y rounded border border-[#444] bg-[#121212] p-2 font-mono text-xs text-white focus:border-blue-500 focus:outline-none disabled:opacity-50"
          />
          <p className="mt-1 text-[10px] text-gray-500">
            Use synthetic data only. Maximum 64 KiB. Samples are not caller messages or confirmation.
          </p>
        </div>
      )}
      <div className="grid grid-cols-2 gap-2">
        <div className="min-w-0">
          <label htmlFor={`${idPrefix}-status`} className="mb-1 block text-[11px] text-gray-300">
            {outcomeOnly ? "Outcome status" : "Sample status"}
          </label>
          <input
            id={`${idPrefix}-status`}
            aria-label={outcomeOnly ? "Outcome status" : "Sample status"}
            type="number"
            min={0}
            max={599}
            step={1}
            required
            value={statusCode}
            onChange={(event) => changeStatus(event.target.value)}
            disabled={isLoading || expired}
            className="w-full rounded border border-[#444] bg-[#121212] px-2 py-1.5 text-xs text-white"
          />
        </div>
        <div className="min-w-0">
          <label htmlFor={`${idPrefix}-outcome`} className="mb-1 block text-[11px] text-gray-300">
            {outcomeOnly ? outcomeLabel : "Result outcome"}
          </label>
          <select
            id={`${idPrefix}-outcome`}
            aria-label={outcomeOnly ? outcomeLabel : "Sample result outcome"}
            value={outcome}
            onChange={(event) => changeOutcome(event.target.value)}
            disabled={isLoading || expired}
            className="w-full rounded border border-[#444] bg-[#121212] px-2 py-1.5 text-xs text-white"
          >
            {!outcomeOnly && <option value="auto">From status</option>}
            <option value="success">{outcomeOnly ? successLabel : "Success"}</option>
            <option value="error">{outcomeOnly ? failureLabel : "Error"}</option>
          </select>
        </div>
      </div>
      <p className="text-[10px] text-gray-500">
        {outcomeOnly
          ? "Choose success (2xx) or failure (non-2xx / 0). No provider response body is accepted."
          : "Status: 200–599, or 0 for a network failure. A sample cannot approve a booking or delivery."}
      </p>
      <button
        type="submit"
        disabled={isLoading || expired || (!outcomeOnly && !dataJson.trim())}
        className="w-full rounded bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading
          ? "Continuing rehearsal…"
          : outcomeOnly ? "Continue with selected outcome" : "Continue with sample"}
      </button>
      {expired && <p role="alert" className="text-xs text-amber-200">This sample request expired. Reset the test.</p>}
    </form>
  );
}
