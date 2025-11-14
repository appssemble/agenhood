import type { HTMLAttributes } from "react";
import { cx } from "../lib/cx";
type Tone = "running" | "dormant" | "warn" | "info" | "ink" | "success" | "brand" | "error";
const TONE: Record<Tone, string> = {
  running: "pill-running",
  dormant: "pill-dormant",
  warn: "pill-warn",
  info: "pill-trans",
  ink: "pill-completed",
  success: "pill-success",
  brand: "pill-brand",
  error: "pill-error",
};
export function Pill({ tone = "dormant", className = "", ...rest }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return <span className={cx("pill", TONE[tone], className)} {...rest} />;
}
