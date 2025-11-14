import type { HTMLAttributes } from "react";
import { cx } from "../lib/cx";
export function Tag({ className = "", ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return <span className={cx("tag", className)} {...rest} />;
}
