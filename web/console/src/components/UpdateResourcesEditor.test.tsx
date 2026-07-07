import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { UpdateResourcesEditor } from "./UpdateResourcesEditor";

const mutateAsync = vi.fn().mockResolvedValue({ id: "ctr_1", status: "running", mem_limit: "4g", cpus: 2, applied: true });

vi.mock("../api/queries", () => ({
  useUpdateResources: () => ({ mutateAsync, isPending: false }),
}));

vi.mock("./Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

beforeEach(() => mutateAsync.mockClear());

test("preselects current values and submits changes", async () => {
  const user = userEvent.setup();
  const onDone = vi.fn();
  render(<UpdateResourcesEditor cid="ctr_1" currentMemLimit="2g" currentCpus={1} onDone={onDone} />);

  expect(screen.getByLabelText(/memory/i)).toHaveTextContent("2 GB");
  expect(screen.getByLabelText(/cpu/i)).toHaveTextContent("1 CPU");

  await user.click(screen.getByLabelText(/memory/i));
  await user.click(screen.getByRole("option", { name: "4 GB" }));
  await user.click(screen.getByLabelText(/cpu/i));
  await user.click(screen.getByRole("option", { name: "2 CPUs" }));
  await user.click(screen.getByRole("button", { name: /^update$/i }));

  await waitFor(() =>
    expect(mutateAsync).toHaveBeenCalledWith({ mem_limit: "4g", cpus: 2 }),
  );
  await waitFor(() => expect(onDone).toHaveBeenCalled());
});

test("injects a non-preset current value so it stays selectable", () => {
  render(<UpdateResourcesEditor cid="ctr_1" currentMemLimit="3g" currentCpus={1.5} onDone={() => {}} />);
  expect(screen.getByLabelText(/memory/i)).toHaveTextContent("3g (current)");
  expect(screen.getByLabelText(/cpu/i)).toHaveTextContent("1.5 (current)");
});

test("cancel collapses without submitting", () => {
  const onDone = vi.fn();
  render(<UpdateResourcesEditor cid="ctr_1" currentMemLimit="2g" currentCpus={1} onDone={onDone} />);
  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onDone).toHaveBeenCalled();
  expect(mutateAsync).not.toHaveBeenCalled();
});
