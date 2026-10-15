import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { MetaOut } from "@/lib/api/types";
import { renderWithIntl } from "@/test/render";

import { useMeta } from "./hooks";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

const META: MetaOut = {
  max_upload_bytes: 20_971_520,
  allowed_extensions: [".pdf", ".md", ".txt"],
  max_pdf_pages: 500,
  max_active_documents_per_user: 10,
  max_storage_bytes_per_user: 1_073_741_824,
  ai: { mode: "offline", chat_model: "mock-heuristic-v1", embedding_model: "mock-hashing-v1" },
};

function UploadLimit() {
  const meta = useMeta();
  if (meta.error) {
    return <button onClick={() => void meta.refetch()}>Try again</button>;
  }
  return <p>{meta.data ? `Up to ${meta.data.max_upload_bytes} bytes` : "Loading limits"}</p>;
}

function Page() {
  const [showSecond, setShowSecond] = useState(false);
  return (
    <>
      <UploadLimit />
      {showSecond ? (
        <UploadLimit />
      ) : (
        <button onClick={() => setShowSecond(true)}>Show another</button>
      )}
    </>
  );
}

describe("useMeta", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("loads GET /meta once for every component that asks", async () => {
    apiFetchMock.mockResolvedValue(META);

    renderWithIntl(
      <>
        <UploadLimit />
        <UploadLimit />
      </>,
    );

    expect(await screen.findAllByText("Up to 20971520 bytes")).toHaveLength(2);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
    expect(apiFetchMock).toHaveBeenCalledWith("/meta");
  });

  it("keeps the answer, so a component mounted later needs no new request", async () => {
    apiFetchMock.mockResolvedValue(META);
    renderWithIntl(<Page />);
    await screen.findByText("Up to 20971520 bytes");

    await userEvent.click(screen.getByRole("button", { name: "Show another" }));

    expect(screen.getAllByText("Up to 20971520 bytes")).toHaveLength(2);
    expect(apiFetchMock).toHaveBeenCalledTimes(1);
  });

  it("reports a failure and loads again on request", async () => {
    apiFetchMock.mockRejectedValueOnce(
      new ApiError({ status: 503, code: "http_error", message: "Service Unavailable" }),
    );
    apiFetchMock.mockResolvedValueOnce(META);
    renderWithIntl(<UploadLimit />);

    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Up to 20971520 bytes")).toBeInTheDocument();
    expect(apiFetchMock).toHaveBeenCalledTimes(2);
  });
});
