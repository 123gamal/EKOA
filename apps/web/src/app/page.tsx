"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { motion } from "motion/react";
import {
  Brain,
  FileSearch,
  Shield,
  Zap,
} from "lucide-react";
import { staggerContainer, staggerItem } from "@/components/ui/motion";

const featureIcons = [Brain, FileSearch, Shield, Zap] as const;
const featureKeys = ["multiAgent", "rag", "security", "workflow"] as const;

export default function HomePage() {
  const t = useTranslations("landing");
  const features = featureKeys.map((key, i) => ({
    icon: featureIcons[i],
    title: t(`features.${key}Title`),
    description: t(`features.${key}Description`),
  }));

  return (
    <div className="min-h-screen">
      <header className="border-b border-[var(--border)]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-2 font-bold text-lg">
            <span className="gradient-brand glow-shadow flex h-8 w-8 items-center justify-center rounded-lg text-white text-sm">
              E
            </span>
            EKOA
          </div>
          <div className="flex gap-3">
            <Link
              href="/login"
              className="rounded-lg px-4 py-2 text-sm font-medium transition-colors hover:bg-[var(--muted)]"
            >
              {t("signIn")}
            </Link>
            <Link
              href="/register"
              className="gradient-brand glow-shadow rounded-lg px-4 py-2 text-sm font-medium text-white transition-transform hover:scale-[1.02]"
            >
              {t("getStarted")}
            </Link>
          </div>
        </div>
      </header>

      <main>
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          className="mx-auto max-w-6xl px-6 py-20 text-center"
        >
          <h1 className="mb-4 text-4xl font-bold tracking-tight sm:text-5xl">
            {t("heroTitleLine1")}
            <br />
            <span className="text-gradient-brand">{t("heroTitleLine2")}</span>
          </h1>
          <p className="mx-auto mb-8 max-w-2xl text-lg text-[var(--muted-foreground)]">
            {t("heroSubtitle")}
          </p>
          <div className="flex justify-center gap-4">
            <Link
              href="/register"
              className="gradient-brand glow-shadow rounded-lg px-8 py-3 font-medium text-white transition-transform hover:scale-[1.02]"
            >
              {t("startFree")}
            </Link>
            <Link
              href="/login"
              className="rounded-lg border border-[var(--border)] px-8 py-3 font-medium transition-colors hover:bg-[var(--muted)]"
            >
              {t("signIn")}
            </Link>
          </div>
        </motion.section>

        <section className="border-t border-[var(--border)] bg-[var(--muted)]/30 py-16">
          <motion.div
            variants={staggerContainer}
            initial="initial"
            whileInView="animate"
            viewport={{ once: true, amount: 0.3 }}
            className="mx-auto grid max-w-6xl gap-8 px-6 sm:grid-cols-2 lg:grid-cols-4"
          >
            {features.map(({ icon: Icon, title, description }) => (
              <motion.div
                key={title}
                variants={staggerItem}
                whileHover={{ y: -4 }}
                className="glass-card glass-card-hover rounded-xl p-6"
              >
                <Icon className="mb-3 h-8 w-8 text-[var(--primary)]" />
                <h3 className="mb-2 font-semibold">{title}</h3>
                <p className="text-sm text-[var(--muted-foreground)]">{description}</p>
              </motion.div>
            ))}
          </motion.div>
        </section>
      </main>

      <footer className="border-t border-[var(--border)] py-6 text-center text-sm text-[var(--muted-foreground)]">
        {t("footer")}
      </footer>
    </div>
  );
}
