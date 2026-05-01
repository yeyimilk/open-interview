import { Outlet } from "react-router-dom";
import { Sparkles } from "lucide-react";
import { ThemeToggle } from "../theme/ThemeToggle";

export function AuthLayout() {
  return (
    <div className="relative flex min-h-screen w-full items-center justify-center bg-background p-4 overflow-hidden">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-gradient-to-br from-primary/10 via-transparent to-transparent" />
      <div className="pointer-events-none absolute -top-40 -right-32 -z-10 h-96 w-96 rounded-full bg-primary/15 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-40 -left-32 -z-10 h-96 w-96 rounded-full bg-primary/10 blur-3xl" />

      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>

      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2 justify-center">
          <div className="grid h-9 w-9 place-items-center rounded-xl bg-primary text-primary-foreground shadow">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="leading-tight text-center">
            <div className="text-base font-semibold tracking-tight">
              Open Interview
            </div>
            <div className="text-xs text-muted-foreground">
              AI interview prep
            </div>
          </div>
        </div>
        <Outlet />
      </div>
    </div>
  );
}
