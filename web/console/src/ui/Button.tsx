import type { ButtonHTMLAttributes } from "react";
import { cx } from "../lib/cx";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "dangerSolid" | "dark";
type Size = "sm" | "md" | "lg" | "icon";

const VARIANT: Record<Variant, string> = {
  primary: "btn-primary",
  secondary: "btn-secondary",
  ghost: "btn-ghost",
  danger: "btn-danger",
  dangerSolid: "btn-danger-solid",
  dark: "btn-dark",
};
const SIZE: Record<Size, string> = {
  sm: "btn-sm",
  md: "",
  lg: "btn-lg",
  icon: "btn-icon",
};

export function Button({
  variant = "secondary", size = "md", className = "", ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button
      className={cx("btn", VARIANT[variant], SIZE[size], className)}
      {...rest}
    />
  );
}
