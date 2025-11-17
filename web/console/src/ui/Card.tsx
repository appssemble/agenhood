import type { HTMLAttributes } from "react";
import { cx } from "../lib/cx";

export function Card({ flush = false, className = "", ...rest }: HTMLAttributes<HTMLDivElement> & { flush?: boolean }) {
  return (
    <div
      className={cx("card", flush && "flush", className)}
      {...rest}
    />
  );
}

export function CardHead({ className = "", ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx("card-head", className)} {...rest} />;
}
