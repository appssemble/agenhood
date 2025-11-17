import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Dropdown, type DropdownOption } from "./Dropdown";

const THREE: DropdownOption[] = [
  { value: "member", label: "Member" },
  { value: "admin", label: "Admin" },
  { value: "owner", label: "Owner" },
];

// Controlled harness so we can assert the value the component reports.
function Harness({
  options = THREE,
  initial = "",
  ...rest
}: {
  options?: DropdownOption[];
  initial?: string;
} & Omit<React.ComponentProps<typeof Dropdown>, "value" | "onChange" | "options">) {
  const [v, setV] = useState(initial);
  return (
    <>
      <Dropdown value={v} onChange={setV} options={options} {...rest} />
      <output data-testid="val">{v}</output>
    </>
  );
}

const manyOptions: DropdownOption[] = Array.from({ length: 12 }, (_, i) => ({
  value: `tz${i}`,
  label: `Zone ${i}`,
}));

test("shows placeholder when no value, then the selected label", () => {
  const { rerender } = render(
    <Dropdown value="" onChange={() => {}} options={THREE} placeholder="Pick…" />,
  );
  expect(screen.getByRole("button")).toHaveTextContent("Pick…");
  rerender(<Dropdown value="admin" onChange={() => {}} options={THREE} placeholder="Pick…" />);
  expect(screen.getByRole("button")).toHaveTextContent("Admin");
});

test("opens on click and selects an option with the mouse", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByRole("button"));
  expect(screen.getByRole("listbox")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("option", { name: "Owner" }));
  expect(screen.getByTestId("val")).toHaveTextContent("owner");
  // menu closes after selection
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

test("keyboard: ArrowDown opens + moves, Enter selects", () => {
  render(<Harness />);
  const trigger = screen.getByRole("button");
  fireEvent.keyDown(trigger, { key: "ArrowDown" }); // opens
  fireEvent.keyDown(trigger, { key: "ArrowDown" }); // member -> admin
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(screen.getByTestId("val")).toHaveTextContent("admin");
});

test("auto search box appears for long lists and filters", async () => {
  render(<Harness options={manyOptions} />);
  await userEvent.click(screen.getByRole("button"));
  const filter = screen.getByLabelText("Filter options");
  expect(filter).toBeInTheDocument();
  await userEvent.type(filter, "Zone 1");
  // "Zone 1", "Zone 10", "Zone 11" match
  expect(screen.getAllByRole("option")).toHaveLength(3);
  await userEvent.clear(filter);
  await userEvent.type(filter, "nope");
  expect(screen.queryByRole("option")).not.toBeInTheDocument();
  expect(screen.getByText("No matches")).toBeInTheDocument();
});

test("searchable={false} hides the box even when long", async () => {
  render(<Harness options={manyOptions} searchable={false} />);
  await userEvent.click(screen.getByRole("button"));
  expect(screen.queryByLabelText("Filter options")).not.toBeInTheDocument();
});

test("disabled option is not selectable and is skipped by keyboard", () => {
  const opts: DropdownOption[] = [
    { value: "a", label: "Alpha" },
    { value: "b", label: "Beta", disabled: true },
    { value: "c", label: "Gamma" },
  ];
  render(<Harness options={opts} />);
  const trigger = screen.getByRole("button");
  fireEvent.keyDown(trigger, { key: "ArrowDown" }); // open, active = Alpha
  fireEvent.keyDown(trigger, { key: "ArrowDown" }); // skip Beta -> Gamma
  fireEvent.keyDown(trigger, { key: "Enter" });
  expect(screen.getByTestId("val")).toHaveTextContent("c");
});

test("applies width to the root", () => {
  const { container } = render(<Harness width={78} />);
  const root = container.querySelector(".dd") as HTMLElement;
  expect(root.style.width).toBe("78px");
});

test("forwards aria-label to the trigger", () => {
  render(<Harness aria-label="Hour" />);
  expect(screen.getByRole("button", { name: "Hour" })).toBeInTheDocument();
});

test("returns focus to the trigger after selecting", async () => {
  render(<Harness />);
  const trigger = screen.getByRole("button");
  await userEvent.click(trigger);
  await userEvent.click(screen.getByRole("option", { name: "Admin" }));
  expect(trigger).toHaveFocus();
});

test("Escape closes and restores focus to the trigger", () => {
  render(<Harness />);
  const trigger = screen.getByRole("button");
  fireEvent.keyDown(trigger, { key: "ArrowDown" });
  fireEvent.keyDown(trigger, { key: "Escape" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

test("search input controls the listbox and tracks the active option", async () => {
  render(<Harness options={manyOptions} />);
  await userEvent.click(screen.getByRole("button"));
  const filter = screen.getByLabelText("Filter options");
  const list = screen.getByRole("listbox");
  expect(list.id).toBeTruthy();
  expect(filter).toHaveAttribute("aria-controls", list.id);
  expect(filter.getAttribute("aria-activedescendant")).toBe(
    screen.getByRole("option", { name: "Zone 0" }).id,
  );
});
