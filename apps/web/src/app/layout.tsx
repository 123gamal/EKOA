import type { Metadata } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { isRtl } from "@/i18n/config";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "EKOA - Enterprise Knowledge Operations Assistant",
  description: "AI-first enterprise knowledge platform with RAG and multi-agent orchestration",
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();

  return (
    <html lang={locale} dir={isRtl(locale) ? "rtl" : "ltr"} suppressHydrationWarning>
      <body className="min-h-screen antialiased">
        <NextIntlClientProvider>
          <Providers>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
