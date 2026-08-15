import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithIntl } from "@/test/render-with-intl";
import userEvent from "@testing-library/user-event";
import LoginPage from "./page";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/lib/api", () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    getMe: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

vi.mock("@/lib/auth", () => ({
  setTokens: vi.fn(),
  clearTokens: vi.fn(),
  getAccessToken: vi.fn(() => null),
}));

import { authApi } from "@/lib/api";
import { setTokens } from "@/lib/auth";

const loginMock = authApi.login as ReturnType<typeof vi.fn>;

describe("LoginForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders email and password fields", () => {
    renderWithIntl(<LoginPage />);
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument();
  });

  it("shows validation errors for empty submit", async () => {
    const user = userEvent.setup();
    renderWithIntl(<LoginPage />);
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(screen.getByText("Email is required")).toBeInTheDocument();
      expect(screen.getByText("Password is required")).toBeInTheDocument();
    });
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("shows an email format error for an invalid email", async () => {
    const user = userEvent.setup();
    renderWithIntl(<LoginPage />);
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(screen.getByText("Enter a valid email address")).toBeInTheDocument();
    });
    expect(loginMock).not.toHaveBeenCalled();
  });

  it("calls authApi.login and stores the token on valid submit", async () => {
    loginMock.mockResolvedValue({ access_token: "jwt-token", refresh_token: "x", token_type: "bearer" });
    const user = userEvent.setup();
    renderWithIntl(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "admin@ekoa.dev");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      expect(loginMock).toHaveBeenCalledWith({ email: "admin@ekoa.dev", password: "hunter2hunter" });
    });
    expect(setTokens).toHaveBeenCalledWith("jwt-token");
    expect(pushMock).toHaveBeenCalledWith("/dashboard");
  });

  it("surfaces an API error in a role=alert banner", async () => {
    loginMock.mockRejectedValue(new Error("Invalid credentials"));
    const user = userEvent.setup();
    renderWithIntl(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "admin@ekoa.dev");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter");
    await user.click(screen.getByRole("button", { name: "Sign In" }));

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Invalid credentials");
    });
  });
});
