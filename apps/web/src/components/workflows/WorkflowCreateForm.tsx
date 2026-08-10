"use client";

import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Play, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import type { WorkflowTemplate } from "@/lib/api";
import {
  createWorkflowSchema,
  type CreateWorkflowValues,
} from "@/lib/validation";

export function WorkflowCreateForm({
  template,
  isSubmitting,
  onSubmit,
  onCancel,
}: {
  template: WorkflowTemplate;
  isSubmitting: boolean;
  onSubmit: (values: CreateWorkflowValues) => void;
  onCancel: () => void;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<CreateWorkflowValues>({
    resolver: zodResolver(createWorkflowSchema),
    defaultValues: { name: template.title, description: "", query: "" },
  });

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h2 id="create-workflow-title" className="font-semibold">
          Create & Run Workflow
        </h2>
        <button
          type="button"
          className="rounded p-1 hover:bg-[var(--muted)]"
          onClick={onCancel}
          aria-label="Close"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <form onSubmit={handleSubmit((values) => onSubmit(values))} noValidate className="space-y-4">
        <p className="text-xs text-[var(--muted-foreground)]">{template.description}</p>
        <Input
          label="Workflow Name"
          id="wf-name"
          error={errors.name?.message}
          {...register("name")}
        />
        <Input
          label="Description (optional)"
          id="wf-desc"
          error={errors.description?.message}
          {...register("description")}
        />
        {template.id === "support-router" && (
          <Input
            label="Sample Support Query"
            id="wf-query"
            error={errors.query?.message}
            placeholder="e.g. How do I reset my account password?"
            {...register("query")}
          />
        )}
        <div className="flex gap-2 pt-2">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                Starting...
              </>
            ) : (
              <>
                <Play className="h-4 w-4" />
                Create & Execute
              </>
            )}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}
