"use client";

import { motion } from "motion/react";

export function DegradedBanner() {
  return (
    <motion.div
      initial={{ height: 0, opacity: 0 }}
      animate={{ height: "auto", opacity: 1 }}
      transition={{ duration: 0.25 }}
      role="status"
      aria-live="polite"
      className="mt-3 overflow-hidden rounded-lg border border-[var(--warning)]/40 bg-[var(--warning)]/10 px-3 py-2 text-xs text-[var(--warning)]"
    >
      <strong>AI temporarily unavailable:</strong> no configured LLM provider responded, so
      EKOA returned a local template answer instead. Check API keys or retry shortly.
    </motion.div>
  );
}
