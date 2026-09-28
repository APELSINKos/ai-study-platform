import { cloneElement, useId, type ReactElement } from "react";

import { cn } from "@/lib/utils";

interface FieldInputProps {
  id?: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  className?: string;
  children: ReactElement<FieldInputProps>;
}

/** Wires a label, an input, an optional hint and an optional error together by id. */
export function Field({ label, hint, error, className, children }: FieldProps) {
  const autoId = useId();
  const inputId = children.props.id ?? autoId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <label htmlFor={inputId} className="text-ink text-sm font-medium">
        {label}
      </label>
      {cloneElement(children, {
        id: inputId,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": describedBy,
      })}
      {hint ? (
        <p id={hintId} className="text-ink-soft text-xs">
          {hint}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} role="alert" className="text-margin text-xs">
          {error}
        </p>
      ) : null}
    </div>
  );
}
