export function DegradedBanner() {
  return (
    <div
      role="status"
      aria-live="polite"
      className="mt-3 rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-xs text-[var(--warning)]"
    >
      <strong>AI temporarily unavailable:</strong> no configured LLM provider responded, so
      EKOA returned a local template answer instead. Check API keys or retry shortly.
    </div>
  );
}
