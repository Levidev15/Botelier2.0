"use client";

import { useState } from "react";
import type { NativePreviewInput, NativePreviewOutcome, PendingNativePreview } from "./nativePreview";

interface NativePreviewCardProps {
  pending: PendingNativePreview;
  isLoading: boolean;
  onSubmit: (input: NativePreviewInput) => Promise<void>;
}

export default function NativePreviewCard({ pending, isLoading, onSubmit }: NativePreviewCardProps) {
  const [dataJson, setDataJson] = useState("");
  const [statusCode, setStatusCode] = useState("200");
  const [outcome, setOutcome] = useState<NativePreviewOutcome>("auto");
  const isMcp = pending.source_kind.startsWith("mcp");
  const expired = pending.expires_in_seconds <= 0;
  const idPrefix = `sample-${pending.request_id}`;
  const sampleInstructions = isMcp
    ? "Paste a synthetic MCP result envelope, including isError, structuredContent or content. Do not run discovery or Test."
    : pending.source_kind === "record"
      ? "Paste sample result data for this simulated Record action. Nothing is written."
      : pending.source_kind === "transfer"
        ? "Paste sample result data for this simulated transfer. No call is moved."
        : "Paste parsed API, integration or saved-tool result data before response mapping. Do not contact the API or provider.";

  return (
    <form
      aria-label="Supply sample action response"
      className="space-y-3 rounded-lg border border-amber-700/60 bg-amber-950/20 p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (!isLoading && !expired) void onSubmit({
          requestId: pending.request_id, dataJson, statusCode: Number(statusCode), outcome,
        });
      }}
    >
      <div>
        <h4 className="text-xs font-semibold text-amber-100">Waiting for a sample response</h4>
        <p className="mt-1 break-all text-[11px] text-gray-400">
          Node: <span className="font-mono text-gray-200">{pending.node_id}</span>
        </p>
        <p className="mt-2 text-[11px] leading-relaxed text-gray-300">
          {sampleInstructions}
          {" "}Your configured mapping and cleanup will run. This does not make an external request.
        </p>
      </div>
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
      <div className="grid grid-cols-2 gap-2">
        <div className="min-w-0">
          <label htmlFor={`${idPrefix}-status`} className="mb-1 block text-[11px] text-gray-300">
            Sample status
          </label>
          <input
            id={`${idPrefix}-status`}
            aria-label="Sample status"
            type="number"
            min={0}
            max={599}
            step={1}
            required
            value={statusCode}
            onChange={(event) => setStatusCode(event.target.value)}
            disabled={isLoading || expired}
            className="w-full rounded border border-[#444] bg-[#121212] px-2 py-1.5 text-xs text-white"
          />
        </div>
        <div className="min-w-0">
          <label htmlFor={`${idPrefix}-outcome`} className="mb-1 block text-[11px] text-gray-300">
            Result outcome
          </label>
          <select
            id={`${idPrefix}-outcome`}
            aria-label="Sample result outcome"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value as NativePreviewOutcome)}
            disabled={isLoading || expired}
            className="w-full rounded border border-[#444] bg-[#121212] px-2 py-1.5 text-xs text-white"
          >
            <option value="auto">From status</option>
            <option value="success">Success</option>
            <option value="error">Error</option>
          </select>
        </div>
      </div>
      <p className="text-[10px] text-gray-500">
        Status: 200–599, or 0 for a network failure. A sample cannot approve a booking or delivery.
      </p>
      <button
        type="submit"
        disabled={isLoading || expired || !dataJson.trim()}
        className="w-full rounded bg-blue-600 px-3 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isLoading ? "Continuing rehearsal…" : "Continue with sample"}
      </button>
      {expired && <p role="alert" className="text-xs text-amber-200">This sample request expired. Reset the test.</p>}
    </form>
  );
}
