import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiFetch } from "@/lib/api/client";
import { ApiError, NETWORK_ERROR_CODE } from "@/lib/api/errors";
import { renderWithIntl } from "@/test/render";

import { SystemStatus } from "./system-status";
import { READINESS_QUERY_KEY } from "./use-readiness";

vi.mock("@/lib/api/client", () => ({ apiFetch: vi.fn() }));

const apiFetchMock = vi.mocked(apiFetch);

describe("SystemStatus", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("shows that it is checking while the first request runs", () => {
    apiFetchMock.mockReturnValue(new Promise(() => {}));

    renderWithIntl(<SystemStatus />);

    expect(screen.getByRole("region", { name: "System status" })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Checking services…");
  });

  it("lists every component with its latency when all is well", async () => {
    apiFetchMock.mockResolvedValue({
      status: "ok",
      checks: {
        database: { status: "ok", latency_ms: 1.2 },
        redis: { status: "ok", latency_ms: 0.4 },
      },
    });

    renderWithIntl(<SystemStatus />);

    // The status region exists from the first render, so wait for its text rather than the role.
    expect(await screen.findByText("Everything is running.")).toHaveAttribute("role", "status");
    const database = screen.getByText("Database").closest("div");
    expect(database).not.toBeNull();
    expect(within(database as HTMLElement).getByText("Ready")).toBeInTheDocument();
    expect(within(database as HTMLElement).getByText("1.2 ms")).toBeInTheDocument();
  });

  it("names the failing component when the backend reports 503", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({
        status: 503,
        code: "http_error",
        message: "Service Unavailable",
        body: {
          status: "unavailable",
          checks: {
            database: { status: "error", latency_ms: null },
            redis: { status: "ok", latency_ms: 0.3 },
          },
        },
      }),
    );

    renderWithIntl(<SystemStatus />);

    expect(await screen.findByText("Some services are unavailable.")).toBeInTheDocument();
    const database = screen.getByText("Database").closest("div");
    expect(within(database as HTMLElement).getByText("Unavailable")).toBeInTheDocument();
  });

  it("offers a retry when the API cannot be reached", async () => {
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "Offline", requestId: null }),
    );

    renderWithIntl(<SystemStatus />);

    expect(await screen.findByText("The API is not responding.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2));
  });

  it("stops reporting success once a later check fails", async () => {
    apiFetchMock.mockResolvedValueOnce({
      status: "ok",
      checks: { database: { status: "ok", latency_ms: 1.2 } },
    });
    apiFetchMock.mockRejectedValue(
      new ApiError({ status: 0, code: NETWORK_ERROR_CODE, message: "Offline", requestId: null }),
    );

    renderWithIntl(<SystemStatus />);
    await screen.findByText("Everything is running.");
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));

    expect(await screen.findByText("The API is not responding.")).toBeInTheDocument();
    expect(screen.queryByText("Database")).not.toBeInTheDocument();
  });

  it("shows a spinner only for a check the user asked for", async () => {
    apiFetchMock.mockResolvedValueOnce({ status: "ok", checks: {} });
    const { queryClient } = renderWithIntl(<SystemStatus />);
    await screen.findByText("Everything is running.");
    apiFetchMock.mockReturnValue(new Promise(() => {}));

    void queryClient.refetchQueries({ queryKey: READINESS_QUERY_KEY });
    await waitFor(() => expect(apiFetchMock).toHaveBeenCalledTimes(2));
    const button = screen.getByRole("button", { name: "Check again" });
    expect(button).not.toHaveAttribute("aria-busy");

    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-busy", "true");
    // A disabled button would drop keyboard focus to the page body.
    expect(button).toBeEnabled();
  });

  it("speaks Russian when the interface does", async () => {
    apiFetchMock.mockResolvedValue({ status: "ok", checks: {} });

    renderWithIntl(<SystemStatus />, { locale: "ru" });

    expect(screen.getByRole("region", { name: "Состояние системы" })).toBeInTheDocument();
    expect(await screen.findByText("Всё работает.")).toBeInTheDocument();
  });
});
