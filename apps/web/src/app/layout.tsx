import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EKOA - Enterprise Knowledge Operations Assistant",
  description: "AI-first enterprise knowledge platform with RAG and multi-agent orchestration",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
