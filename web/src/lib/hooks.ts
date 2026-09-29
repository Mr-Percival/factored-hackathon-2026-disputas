import { useCallback, useEffect, useState, useSyncExternalStore } from "react";

export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (cb: () => void) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", cb);
      return () => {
        mql.removeEventListener("change", cb);
      };
    },
    [query],
  );
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    () => false,
  );
}

export type Theme = "light" | "dark";
const THEME_KEY = "bankagent-theme";

function readStoredTheme(): Theme | null {
  try {
    const v = window.localStorage.getItem(THEME_KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null; // almacenamiento bloqueado (modo privado): se usa el del sistema
  }
}

/** Tema claro/oscuro: sigue a prefers-color-scheme hasta que el usuario elige uno (se recuerda). */
export function useTheme(): [Theme, () => void] {
  const systemDark = useMediaQuery("(prefers-color-scheme: dark)");
  const [chosen, setChosen] = useState<Theme | null>(readStoredTheme);
  const theme: Theme = chosen ?? (systemDark ? "dark" : "light");

  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove("light", "dark");
    if (chosen) root.classList.add(chosen);
  }, [chosen]);

  const toggle = useCallback(() => {
    const next: Theme = theme === "dark" ? "light" : "dark";
    setChosen(next);
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      /* sin persistencia: el tema dura lo que la pestaña */
    }
  }, [theme]);

  return [theme, toggle];
}
