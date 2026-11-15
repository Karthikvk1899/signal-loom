import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { App } from "./main";
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("operator console", () => {
  it("keeps actions gated until connected", () => {
    render(<App />);
    expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
    expect(screen.queryByText("Propose revision")).not.toBeInTheDocument();
  });
  it("reports API failures and never stores the credential", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue({
          ok: false,
          json: async () => ({ detail: "invalid credential" }),
        }),
    );
    render(<App />);
    fireEvent.change(screen.getByLabelText("Session credential"), {
      target: { value: "test-token" },
    });
    fireEvent.click(screen.getByText("Connect"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "invalid credential",
    );
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });
  it("loads scoped revisions and clears session on disconnect", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockImplementation((url: string) =>
          Promise.resolve({
            ok: true,
            json: async () =>
              url === "/v1/environments"
                ? [{ name: "prod", generation: 0, active_revision: null }]
                : [],
          }),
        ),
    );
    render(<App />);
    fireEvent.change(screen.getByLabelText("Session credential"), {
      target: { value: "secret" },
    });
    fireEvent.click(screen.getByText("Connect"));
    await screen.findByText("Propose revision");
    fireEvent.click(screen.getByText("Disconnect"));
    await waitFor(() =>
      expect(screen.getByLabelText("Session credential")).toHaveValue(""),
    );
    expect(screen.queryByText("Propose revision")).not.toBeInTheDocument();
  });
});
