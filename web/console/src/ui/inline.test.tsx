import { render, screen } from "@testing-library/react";
import { Tag } from "./Tag";
import { Chip } from "./Chip";
import { Kbd } from "./Kbd";
import { Pill } from "./Pill";

test("inline primitives render their content", () => {
  render(<><Tag>full</Tag><Chip>step 6</Chip><Kbd>⌘K</Kbd><Pill tone="running">live</Pill></>);
  expect(screen.getByText("full").className).toMatch(/\btag\b/);
  expect(screen.getByText("step 6")).toBeInTheDocument();
  expect(screen.getByText("⌘K").tagName).toBe("KBD");
  expect(screen.getByText("live").className).toMatch(/pill-running/);
});
