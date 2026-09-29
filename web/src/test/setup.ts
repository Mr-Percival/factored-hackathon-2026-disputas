import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, vi } from "vitest";

// jsdom no implementa matchMedia ni scrollIntoView.
export const media = { wide: true, dark: false };

beforeEach(() => {
  media.wide = true;
  media.dark = false;
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: query.includes("min-width") ? media.wide : query.includes("dark") ? media.dark : false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
  Element.prototype.scrollIntoView = vi.fn();
  document.documentElement.className = "";
  window.localStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
