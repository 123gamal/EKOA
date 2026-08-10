"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { CheckCircle2, UserCheck, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import {
  approvalDecisionSchema,
  type ApprovalDecisionValues,
} from "@/lib/validation";

export function ApprovalPanel({
  workflowName,
  isSubmitting,
  onSubmit,
  onReject,
}: {
  workflowName: string;
  isSubmitting: boolean;
  onSubmit: (values: ApprovalDecisionValues) => void;
  onReject: (values: ApprovalDecisionValues) => void;
}) {
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<ApprovalDecisionValues>({
    resolver: zodResolver(approvalDecisionSchema),
    defaultValues: { reason: "" },
  });

  return (
    <div className="rounded-xl border border-amber-500/50 bg-amber-500/5 p-6">
      <div className="flex items-center gap-2 mb-3">
        <UserCheck className="h-5 w-5 text-amber-500" />
        <h3 id="approval-title" className="font-semibold text-sm">
          Run paused — awaiting human approval
        </h3>
        <span className="ml-auto text-[11px] uppercase text-amber-500">Decision required</span>
      </div>
      <p className="text-xs text-[var(--muted-foreground)] mb-3">
        Sensitive data was detected in <strong>{workflowName}</strong>. Approving resumes the run
        and records the compliance result in the audit log; rejecting terminates it.
      </p>
      <form onSubmit={handleSubmit((values) => onSubmit(values))} noValidate className="space-y-4">
        <Input
          label="Reason / comment (optional)"
          id="decision-reason"
          error={errors.reason?.message}
          placeholder="e.g. Reviewed the finding — no true leak"
          {...register("reason")}
        />
        <div className="flex gap-2 pt-1">
          <Button type="submit" disabled={isSubmitting}>
            <CheckCircle2 className="h-4 w-4" />
            Approve
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={isSubmitting}
            onClick={() => onReject({ reason: getValues("reason") || "" })}
          >
            <X className="h-4 w-4" />
            Reject
          </Button>
        </div>
      </form>
    </div>
  );
}
