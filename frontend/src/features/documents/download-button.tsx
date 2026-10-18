"use client";

import { DownloadSimpleIcon } from "@phosphor-icons/react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { DocumentOut } from "@/lib/api/types";

import { fetchDocumentFile } from "./api";
import { documentErrorMessage } from "./error-message";

/** Hands the file to the browser as a download under the given name. */
function saveFile(file: Blob, filename: string): void {
  const url = URL.createObjectURL(file);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoked after the click has been handled: revoking at once can cancel the download.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/**
 * Downloads the file as it was uploaded. It is fetched through the API client rather than
 * linked to, so an expired session is renewed on the way, as for every other request.
 */
export function DownloadButton({ document }: { document: DocumentOut }) {
  const t = useTranslations("Documents.detail");
  const tErrors = useTranslations("Documents.errors");
  const download = useMutation({
    mutationFn: async () => {
      saveFile(await fetchDocumentFile(document.id), document.original_filename);
    },
  });

  return (
    <>
      <Button
        variant="secondary"
        size="sm"
        isLoading={download.isPending}
        onClick={() => download.mutate()}
      >
        {download.isPending ? null : <DownloadSimpleIcon aria-hidden />}
        {t("download")}
      </Button>
      {download.isError ? (
        // Last in the row, so the sentence sits under all the buttons.
        <p role="alert" className="text-margin order-last basis-full text-sm">
          {documentErrorMessage(download.error, "download", tErrors)}
        </p>
      ) : null}
    </>
  );
}
