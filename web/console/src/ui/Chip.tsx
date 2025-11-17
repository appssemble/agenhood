import type { HTMLAttributes } from "react";
import { cx } from "../lib/cx";
export function Chip({ className = "", ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cx("chip", className)} {...rest} />;
}
