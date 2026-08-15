import { render, type RenderResult } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import type { ReactElement } from "react";
import messages from "../../messages/en.json";

/** Same render() but wrapped in the NextIntlClientProvider every real page
 * gets from the root layout — components using useTranslations() throw
 * without it. English messages only; component tests aren't the place to
 * verify translated copy (that's Playwright's job, see e2e/). */
export function renderWithIntl(ui: ReactElement): RenderResult {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {ui}
    </NextIntlClientProvider>
  );
}
