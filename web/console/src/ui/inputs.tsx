import type { InputHTMLAttributes, TextareaHTMLAttributes, SelectHTMLAttributes } from "react";
import { cx } from "../lib/cx";

export function Input({ className = "", ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx("input", className)} {...p} />;
}
export function Textarea({ className = "", ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cx("textarea", className)} {...p} />;
}
/** @deprecated Use the styled `Dropdown` component (src/ui/Dropdown.tsx) for fixed-choice fields. */
export function Select({ className = "", ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cx("select", className)} {...p} />;
}
export function Checkbox({ className = "", ...p }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="checkbox" className={className} {...p} />;
}
export function Switch({ on, className = "", ...p }: { on?: boolean } & React.HTMLAttributes<HTMLButtonElement>) {
  return (
    <button type="button" role="switch" aria-checked={!!on}
      className={cx("switch", on && "on", className)} {...p}>
      <span />
    </button>
  );
}
