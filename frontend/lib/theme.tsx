"use client";

import { useCallback, useEffect, useState } from "react";

export type ThemeChoice = "light" | "dark" | "system";
const KEY = "smartroute.theme";

/** Runs before the first paint (inlined in the root layout) so the page never flashes the wrong theme. */
export const THEME_INIT = `(function(){try{var t=localStorage.getItem("${KEY}");if(t!=="light"&&t!=="dark"){t=window.matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"}document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}})();`;

const systemTheme = () => (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");

function apply(choice: ThemeChoice) {
  document.documentElement.dataset.theme = choice === "system" ? systemTheme() : choice;
}

/** Current theme choice and a setter that persists it (system = follow the OS). */
export function useTheme() {
  const [choice, setChoice] = useState<ThemeChoice>("system");
  const [resolved, setResolved] = useState<"light" | "dark">("light");

  useEffect(() => {
    let stored: string | null = null;
    try {
      stored = localStorage.getItem(KEY);
    } catch {
      /* storage blocked */
    }
    setChoice(stored === "light" || stored === "dark" ? stored : "system");
    setResolved(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  }, []);

  useEffect(() => {
    if (choice !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      apply("system");
      setResolved(systemTheme());
    };
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [choice]);

  const set = useCallback((next: ThemeChoice) => {
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      /* the choice lasts for this page only */
    }
    apply(next);
    setChoice(next);
    setResolved(document.documentElement.dataset.theme === "dark" ? "dark" : "light");
  }, []);

  return { choice, resolved, set };
}
