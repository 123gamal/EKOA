import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { DegradedBanner } from "./DegradedBanner";

describe("DegradedBanner", () => {
  it("announces the degraded-answer status via aria-live", () => {
    render(<DegradedBanner />);
    const banner = screen.getByText(/AI temporarily unavailable/i);
    expect(banner).toBeInTheDocument();
    expect(banner.closest("[aria-live='polite']")).not.toBeNull();
  });

  it("renders the fallback explanation text", () => {
    render(<DegradedBanner />);
    expect(screen.getByText(/local template answer/i)).toBeInTheDocument();
  });
});
