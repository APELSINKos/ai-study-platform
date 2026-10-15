"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useMemo, useState, type BaseSyntheticEvent } from "react";
import { useForm, type FieldErrors } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { IndexCard, IndexCardBody, IndexCardHeader } from "@/components/ui/index-card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { matchServerFields } from "@/features/auth/server-fields";
import { ApiError } from "@/lib/api/errors";

import { workspaceErrorMessage } from "./error-message";
import { useCreateWorkspace } from "./hooks";
import { toCreateRequest, workspaceFormSchema, type WorkspaceFormValues } from "./schemas";

const FIELD_BY_SERVER_NAME: Readonly<Record<string, keyof WorkspaceFormValues>> = {
  name: "name",
  description: "description",
  exam_date: "examDate",
};

// The last day the backend's date type can hold; it also keeps the picker's year to four digits.
const LATEST_EXAM_DATE = "9999-12-31";

/**
 * A date input that is only partly filled in reports an empty value, the same as a cleared one;
 * only its validity tells them apart.
 */
function hasHalfTypedExamDate(event?: BaseSyntheticEvent): boolean {
  const form: unknown = event?.target;
  if (!(form instanceof HTMLFormElement)) {
    return false;
  }
  const input = form.elements.namedItem("examDate");
  return input instanceof HTMLInputElement && input.validity.badInput;
}

interface CreateWorkspaceFormProps {
  /** Offered when the page has something to return to; without it the form stays put. */
  onCancel?: () => void;
  /** Puts the cursor in the name field at once, for a form the user has just asked for. */
  autoFocus?: boolean;
  className?: string;
}

export function CreateWorkspaceForm({
  onCancel,
  autoFocus = false,
  className,
}: CreateWorkspaceFormProps) {
  const t = useTranslations("Workspaces.form");
  const tValidation = useTranslations("Workspaces.validation");
  const tErrors = useTranslations("Workspaces.errors");
  const router = useRouter();
  const create = useCreateWorkspace();
  const titleId = useId();
  const [formError, setFormError] = useState<string | null>(null);
  const schema = useMemo(() => workspaceFormSchema(tValidation), [tValidation]);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<WorkspaceFormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", description: "", examDate: "" },
  });
  // Still busy after success: the form stays until the new workspace's page replaces it, and a
  // second click in between must not create a second workspace.
  const isBusy = create.isPending || create.isSuccess;

  function flagHalfTypedExamDate(event: BaseSyntheticEvent | undefined, shouldFocus: boolean) {
    const halfTyped = hasHalfTypedExamDate(event);
    if (halfTyped) {
      setError("examDate", { message: tValidation("examDateIncomplete") }, { shouldFocus });
    }
    return halfTyped;
  }

  function onValid(values: WorkspaceFormValues, event?: BaseSyntheticEvent) {
    if (isBusy || flagHalfTypedExamDate(event, true)) {
      return;
    }
    setFormError(null);
    create.mutate(toCreateRequest(values), {
      onSuccess: (workspace) => router.push(`/workspaces/${workspace.id}`),
      onError: showFailure,
    });
  }

  // The form then focuses its first invalid field itself.
  function onInvalid(_errors: FieldErrors<WorkspaceFormValues>, event?: BaseSyntheticEvent) {
    flagHalfTypedExamDate(event, false);
  }

  function showFailure(error: unknown) {
    if (error instanceof ApiError && error.code === "validation_error") {
      // The backend's wording is English-only, so the fields get theirs from the catalog.
      const { fields, hasUnmatched } = matchServerFields(error.details, FIELD_BY_SERVER_NAME);
      for (const [index, field] of fields.entries()) {
        setError(field, { message: tValidation("fieldRejected") }, { shouldFocus: index === 0 });
      }
      if (fields.length > 0 && !hasUnmatched) {
        return;
      }
    }
    setFormError(workspaceErrorMessage(error, "create", tErrors));
  }

  return (
    <IndexCard className={className}>
      <IndexCardHeader>
        <h2 id={titleId} className="font-display text-lg font-semibold">
          {t("title")}
        </h2>
      </IndexCardHeader>
      <IndexCardBody
        as="form"
        aria-labelledby={titleId}
        onSubmit={handleSubmit(onValid, onInvalid)}
        noValidate
        className="flex flex-col gap-4"
      >
        <Field label={t("name")} error={errors.name?.message}>
          <Input type="text" autoComplete="off" autoFocus={autoFocus} {...register("name")} />
        </Field>
        <Field
          label={t("description")}
          hint={t("descriptionHint")}
          error={errors.description?.message}
        >
          <Textarea rows={3} {...register("description")} />
        </Field>
        <Field label={t("examDate")} hint={t("examDateHint")} error={errors.examDate?.message}>
          <Input type="date" max={LATEST_EXAM_DATE} className="sm:w-56" {...register("examDate")} />
        </Field>
        {formError ? (
          <p role="alert" className="text-margin text-sm">
            {formError}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <Button type="submit" variant="primary" isLoading={isBusy}>
            {t("submit")}
          </Button>
          {onCancel ? (
            <Button variant="ghost" onClick={onCancel}>
              {t("cancel")}
            </Button>
          ) : null}
        </div>
      </IndexCardBody>
    </IndexCard>
  );
}
