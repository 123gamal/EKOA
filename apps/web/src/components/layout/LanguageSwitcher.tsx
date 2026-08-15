"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Languages } from "lucide-react";
import { setUserLocale } from "@/i18n/locale";
import { locales, type Locale } from "@/i18n/config";

export function LanguageSwitcher() {
  const locale = useLocale();
  const t = useTranslations("language");
  const router = useRouter();
  const [isPending, startTransition] = useTransition();

  function handleChange(next: Locale) {
    if (next === locale) return;
    startTransition(async () => {
      await setUserLocale(next);
      router.refresh();
    });
  }

  return (
    <div className="relative inline-flex items-center gap-1 rounded-lg border border-[var(--border)] p-1">
      <Languages className="ms-1 h-4 w-4 text-[var(--muted-foreground)]" />
      {locales.map((l) => (
        <button
          key={l}
          type="button"
          disabled={isPending}
          onClick={() => handleChange(l)}
          className={
            "rounded-md px-2 py-1 text-xs font-medium transition-colors " +
            (l === locale
              ? "bg-[var(--primary)] text-[var(--primary-foreground)]"
              : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]")
          }
        >
          {t(l === "en" ? "english" : "arabic")}
        </button>
      ))}
    </div>
  );
}
