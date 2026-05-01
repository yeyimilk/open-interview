import { createContext, useContext, useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";

interface Ctx {
  theme: Theme;
  setTheme: (t: Theme) => void;
  resolved: "light" | "dark";
}

const ThemeCtx = createContext<Ctx | null>(null);

interface Props {
  children: React.ReactNode;
  defaultTheme?: Theme;
  storageKey?: string;
}

export function ThemeProvider({
  children,
  defaultTheme = "system",
  storageKey = "oi-theme",
}: Props) {
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      const stored = localStorage.getItem(storageKey) as Theme | null;
      return stored || defaultTheme;
    } catch {
      return defaultTheme;
    }
  });
  const [resolved, setResolved] = useState<"light" | "dark">("light");

  useEffect(() => {
    const root = document.documentElement;

    function apply(t: Theme) {
      const sysDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      const next = t === "system" ? (sysDark ? "dark" : "light") : t;
      root.classList.remove("light", "dark");
      root.classList.add(next);
      setResolved(next);
    }

    apply(theme);

    if (theme === "system") {
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      const onChange = () => apply("system");
      mq.addEventListener("change", onChange);
      return () => mq.removeEventListener("change", onChange);
    }
  }, [theme]);

  function setTheme(t: Theme) {
    try {
      localStorage.setItem(storageKey, t);
    } catch {
      /* ignore */
    }
    setThemeState(t);
  }

  return (
    <ThemeCtx.Provider value={{ theme, setTheme, resolved }}>
      {children}
    </ThemeCtx.Provider>
  );
}

export function useTheme(): Ctx {
  const v = useContext(ThemeCtx);
  if (!v) throw new Error("useTheme must be used within ThemeProvider");
  return v;
}
