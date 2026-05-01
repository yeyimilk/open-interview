import {
  Briefcase,
  FileText,
  Folders,
  GraduationCap,
  Home,
  LogOut,
  Menu,
  Settings,
  Sparkles,
  Mic,
} from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "../../auth/AuthContext";
import { cn } from "../../lib/cn";
import { ThemeToggle } from "../theme/ThemeToggle";
import { Avatar, AvatarFallback } from "../ui/avatar";
import { Button } from "../ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";
import { Separator } from "../ui/separator";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "../ui/sheet";
import { TooltipProvider } from "../ui/tooltip";

interface NavItem {
  to: string;
  label: string;
  icon: React.ElementType;
}

const NAV: NavItem[] = [
  { to: "/", label: "Home", icon: Home },
  { to: "/projects", label: "Projects", icon: Folders },
  { to: "/resumes", label: "Resume", icon: FileText },
  { to: "/mentor", label: "Mentor", icon: GraduationCap },
  { to: "/interviewer", label: "Interview", icon: Mic },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-2 px-3 py-4 group">
      <div className="grid h-8 w-8 place-items-center rounded-xl bg-primary text-primary-foreground shadow-sm group-hover:scale-105 transition-transform">
        <Sparkles className="h-4 w-4" />
      </div>
      <div className="leading-tight">
        <div className="text-sm font-semibold tracking-tight">
          Open Interview
        </div>
        <div className="text-xs text-muted-foreground">
          AI interview prep
        </div>
      </div>
    </Link>
  );
}

function NavList({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <nav className="flex-1 space-y-1 px-2">
      {NAV.map((item) => {
        const Icon = item.icon;
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                isActive
                  ? "bg-primary/10 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-foreground"
              )
            }
          >
            <Icon className="h-4 w-4" />
            {item.label}
          </NavLink>
        );
      })}
    </nav>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  if (!user) {
    return (
      <div className="flex flex-col gap-2 p-3">
        <Button asChild className="w-full">
          <Link to="/login">Sign in</Link>
        </Button>
        <Button asChild variant="outline" className="w-full">
          <Link to="/register">Create account</Link>
        </Button>
      </div>
    );
  }
  const initials = (user.display_name || user.email || "U")
    .split(/\s+/)
    .map((s) => s[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="p-2">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="ghost"
            className="w-full justify-start gap-3 px-2 py-2 h-auto"
          >
            <Avatar className="h-8 w-8">
              <AvatarFallback className="bg-primary/10 text-primary">
                {initials}
              </AvatarFallback>
            </Avatar>
            <div className="flex flex-col items-start leading-tight overflow-hidden">
              <span className="text-sm font-medium truncate max-w-[10rem]">
                {user.display_name || user.email}
              </span>
              <span className="text-xs text-muted-foreground truncate max-w-[10rem]">
                {user.tier || "free"} plan
              </span>
            </div>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="top" align="start" className="w-56">
          <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem asChild>
            <Link to="/settings">
              <Settings className="mr-2 h-4 w-4" /> Settings
            </Link>
          </DropdownMenuItem>
          <DropdownMenuItem asChild>
            <Link to="/projects">
              <Briefcase className="mr-2 h-4 w-4" /> Projects
            </Link>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={logout} className="text-destructive">
            <LogOut className="mr-2 h-4 w-4" /> Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <Brand />
      <Separator />
      <div className="py-3">
        <NavList onNavigate={onNavigate} />
      </div>
      <div className="mt-auto">
        <Separator />
        <UserMenu />
      </div>
    </div>
  );
}

function TopBar() {
  const { pathname } = useLocation();
  const segs = pathname.split("/").filter(Boolean);
  return (
    <div className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/80 px-4 backdrop-blur">
      <Sheet>
        <SheetTrigger asChild>
          <Button variant="ghost" size="icon" className="md:hidden">
            <Menu className="h-5 w-5" />
          </Button>
        </SheetTrigger>
        <SheetContent side="left" className="w-72 p-0">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <Sidebar />
        </SheetContent>
      </Sheet>
      <nav className="text-sm text-muted-foreground flex items-center gap-1.5">
        <Link to="/" className="hover:text-foreground">
          Home
        </Link>
        {segs.map((s, i) => (
          <span key={i} className="flex items-center gap-1.5">
            <span className="opacity-40">/</span>
            <Link
              to={"/" + segs.slice(0, i + 1).join("/")}
              className="hover:text-foreground capitalize"
            >
              {decodeURIComponent(s)}
            </Link>
          </span>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2">
        <ThemeToggle />
      </div>
    </div>
  );
}

export function AppShell() {
  return (
    <TooltipProvider delayDuration={250}>
      <div className="flex min-h-screen w-full">
        <aside className="hidden md:flex w-64 shrink-0 flex-col border-r bg-card/30">
          <Sidebar />
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <TopBar />
          <main className="flex-1 overflow-x-hidden">
            <div className="mx-auto w-full max-w-7xl p-4 md:p-8 animate-fade-in">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
