import { cx } from "../lib/cx";
type Tone = "default" | "amber" | "mint";
const TONE: Record<Tone, string> = {
  default: "",
  amber: "amber",
  mint: "mint",
};
export function Note({ tone = "default", className = "", ...rest }: React.HTMLAttributes<HTMLDivElement> & { tone?: Tone }) {
  return <div className={cx("note", TONE[tone], className)} {...rest} />;
}
