"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { authApi } from "@/lib/api";
import { registerSchema, type RegisterValues } from "@/lib/validation";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardContent } from "@/components/ui/Card";

export default function RegisterPage() {
  const t = useTranslations("auth.register");
  const router = useRouter();

  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { fullName: "", email: "", password: "" },
  });

  async function onSubmit(values: RegisterValues) {
    try {
      await authApi.register({ email: values.email, password: values.password, full_name: values.fullName });
      router.push("/login");
    } catch (err: unknown) {
      setError("root", {
        message: err instanceof Error ? err.message : "Registration failed",
      });
    }
  }

  return (
    <Card className="w-full max-w-md">
      <CardContent className="pt-6">
        <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
          <div className="mb-6 text-center">
            <h1 className="text-gradient-brand text-2xl font-bold">{t("title")}</h1>
            <p className="mt-1 text-sm text-[var(--muted-foreground)]">
              {t("subtitle")}
            </p>
          </div>

          {errors.root && (
            <div
              role="alert"
              className="rounded-lg bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] px-4 py-3 text-sm text-[var(--destructive)]"
            >
              {errors.root.message}
            </div>
          )}

          <Input
            label={t("fullName")}
            id="fullName"
            type="text"
            autoComplete="name"
            error={errors.fullName?.message}
            {...register("fullName")}
          />

          <Input
            label={t("email")}
            id="email"
            type="email"
            autoComplete="email"
            error={errors.email?.message}
            {...register("email")}
          />

          <Input
            label={t("password")}
            id="password"
            type="password"
            autoComplete="new-password"
            error={errors.password?.message}
            {...register("password")}
          />

          <Button type="submit" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? t("submitting") : t("submit")}
          </Button>

          <p className="text-center text-sm text-[var(--muted-foreground)]">
            {t("haveAccount")}{" "}
            <Link href="/login" className="text-[var(--primary)] hover:underline">
              {t("login")}
            </Link>
          </p>
        </form>
      </CardContent>
    </Card>
  );
}
