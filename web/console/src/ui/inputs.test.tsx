import { render, screen } from "@testing-library/react";
import { Field } from "./Field";
import { Input, Textarea, Select, Checkbox, Switch } from "./inputs";

test("Field renders label + hint and links the control", () => {
  render(<Field label="Model" hint="constrained" htmlFor="m"><Input id="m" /></Field>);
  expect(screen.getByText("Model")).toBeInTheDocument();
  expect(screen.getByText("constrained")).toBeInTheDocument();
  expect(screen.getByLabelText("Model")).toBeInTheDocument();
});

test("controls render", () => {
  render(<><Textarea aria-label="t" /><Select aria-label="s"><option>a</option></Select>
    <Checkbox aria-label="c" /><Switch on aria-label="sw" /></>);
  expect(screen.getByLabelText("t").tagName).toBe("TEXTAREA");
  expect(screen.getByLabelText("s").tagName).toBe("SELECT");
});
