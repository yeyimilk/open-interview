import { Toaster as SonnerToaster, type ToasterProps } from "sonner";
import { useTheme } from "../theme/ThemeProvider";

export function Toaster(props: ToasterProps) {
  const { resolved } = useTheme();
  return (
    <SonnerToaster
      theme={resolved}
      toastOptions={{
        classNames: {
          toast:
            "group toast group-[.toaster]:bg-popover group-[.toaster]:text-popover-foreground group-[.toaster]:border group-[.toaster]:shadow-lg group-[.toaster]:rounded-xl",
          description: "group-[.toast]:text-muted-foreground",
          actionButton:
            "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
          cancelButton:
            "group-[.toast]:bg-muted group-[.toast]:text-muted-foreground",
        },
      }}
      {...props}
    />
  );
}
