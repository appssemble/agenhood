import type { HTMLAttributes } from "react";
export function Kbd({ className = "", ...rest }: HTMLAttributes<HTMLElement>) {
  return <kbd className={className || undefined} {...rest} />;
}
