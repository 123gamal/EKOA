export const locales = ["en", "ar"] as const;
export type Locale = (typeof locales)[number];
export const defaultLocale: Locale = "en";

export const rtlLocales: readonly Locale[] = ["ar"];

export function isRtl(locale: string): boolean {
  return (rtlLocales as readonly string[]).includes(locale);
}
