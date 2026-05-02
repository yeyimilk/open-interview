import { Check, Pencil, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { cn } from "../../lib/cn";
import { Button } from "../ui/button";
import { Input } from "../ui/input";

interface Props {
  value: string | null;
  /** Called with the trimmed new value (or empty string for "clear"). */
  onSave: (next: string) => Promise<void>;
  placeholder?: string;
  /** When true, the trigger pencil + edit affordance is hidden. */
  readOnly?: boolean;
  /** Visual size — matches the existing PageHeader title. */
  className?: string;
}

/**
 * Inline-editable title used in chat / mentor / interviewer page headers.
 *
 * Click the title (or the pencil icon) to enter edit mode; Enter saves,
 * Escape cancels, blur saves (matches what ChatGPT and Linear do).
 */
export function EditableTitle({
  value,
  onSave,
  placeholder = "Untitled",
  readOnly,
  className,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setDraft(value ?? "");
  }, [value]);

  useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select();
    }
  }, [editing]);

  async function commit() {
    const next = draft.trim();
    if ((next || "") === (value || "")) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(next);
      setEditing(false);
    } catch (e) {
      toast.error("Couldn't save title", {
        description: (e as Error).message,
      });
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <span
        className={cn(
          "inline-flex items-center gap-1.5 group min-w-0",
          className
        )}
      >
        <span
          onClick={readOnly ? undefined : () => setEditing(true)}
          className={cn(
            "truncate",
            !readOnly && "cursor-text hover:underline decoration-dotted",
            !value && "text-muted-foreground italic font-normal"
          )}
          title={readOnly ? undefined : "Click to rename"}
        >
          {value || placeholder}
        </span>
        {!readOnly && (
          <button
            type="button"
            onClick={() => setEditing(true)}
            aria-label="Rename"
            className="opacity-0 group-hover:opacity-60 hover:!opacity-100 transition-opacity"
          >
            <Pencil className="h-4 w-4" />
          </button>
        )}
      </span>
    );
  }

  return (
    <span className={cn("inline-flex items-center gap-1.5 min-w-0", className)}>
      <Input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            void commit();
          } else if (e.key === "Escape") {
            e.preventDefault();
            setDraft(value ?? "");
            setEditing(false);
          }
        }}
        onBlur={() => void commit()}
        disabled={saving}
        placeholder={placeholder}
        className="h-9 max-w-md text-2xl md:text-3xl font-semibold tracking-tight"
      />
      <Button
        size="icon"
        variant="ghost"
        onClick={() => void commit()}
        disabled={saving}
        aria-label="Save"
      >
        <Check className="h-4 w-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        onClick={() => {
          setDraft(value ?? "");
          setEditing(false);
        }}
        disabled={saving}
        aria-label="Cancel"
      >
        <X className="h-4 w-4" />
      </Button>
    </span>
  );
}
