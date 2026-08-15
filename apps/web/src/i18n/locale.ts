"use server";

import { cookies } from "next/headers";
import { defaultLocale, locales, type Locale } from "./config";

const COOKIE_NAME = "ekoa_locale";

export async function getUserLocale(): Promise<Locale> {
  const value = (await cookies()).get(COOKIE_NAME)?.value;
  return (locales as readonly string[]).includes(value ?? "")
    ? (value as Locale)
    : defaultLocale;
}

export async function setUserLocale(locale: Locale): Promise<void> {
  (await cookies()).set(COOKIE_NAME, locale, { path: "/", maxAge: 60 * 60 * 24 * 365 });
}
