import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RegisterPage from "./page";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/api", () => ({
  authApi: {
    register: vi.fn(),
    login: vi.fn(),
    getMe: vi.fn(),
    me: vi.fn(),
    logout: vi.fn(),
  },
}));

import { authApi } from "@/lib/api";

const registerMock = authApi.register as ReturnType<typeof vi.fn>;

describe("RegisterForm", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all registration fields", () => {
    render(<RegisterPage />);
    expect(screen.getByLabelText("Full Name")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });

  it("rejects a password shorter than 8 characters", async () => {
    const user = userEvent.setup();
    render(<RegisterPage />);

    await user.type(screen.getByLabelText("Full Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@ekoa.dev");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create Account" }));

    await waitFor(() => {
      expect(screen.getByText("Password must be at least 8 characters")).toBeInTheDocument();
    });
    expect(registerMock).not.toHaveBeenCalled();
  });

  it("calls authApi.register and navigates to login on valid submit", async () => {
    registerMock.mockResolvedValue({});
    const user = userEvent.setup();
    render(<RegisterPage />);

    await user.type(screen.getByLabelText("Full Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@ekoa.dev");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter");
    await user.click(screen.getByRole("button", { name: "Create Account" }));

    await waitFor(() => {
      expect(registerMock).toHaveBeenCalledWith({
        email: "ada@ekoa.dev",
        password: "hunter2hunter",
        full_name: "Ada Lovelace",
      });
    });
    expect(pushMock).toHaveBeenCalledWith("/login");
  });

  it("surfaces an API error in a role=alert banner", async () => {
    registerMock.mockRejectedValue(new Error("Email already registered"));
    const user = userEvent.setup();
    render(<RegisterPage />);

    await user.type(screen.getByLabelText("Full Name"), "Ada Lovelace");
    await user.type(screen.getByLabelText("Email"), "ada@ekoa.dev");
    await user.type(screen.getByLabelText("Password"), "hunter2hunter");
    await user.click(screen.getByRole("button", { name: "Create Account" }));

    await waitFor(() => {
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent("Email already registered");
    });
  });
});
