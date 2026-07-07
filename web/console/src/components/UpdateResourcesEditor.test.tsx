import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { UpdateResourcesEditor } from "./UpdateResourcesEditor";

const mutateAsync = vi.fn().mockResolvedValue({ id: "ctr_1", status: "running", mem_limit: "3g", cpus: 1.5, applied: true });

vi.mock("../api/queries", () => ({
  useUpdateResources: () => ({ mutateAsync, isPending: false }),
}));

vi.mock("./Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

beforeEach(() => mutateAsync.mockClear());

test("preselects current values and submits changes", async () => {
  const onDone = vi.fn();
  render(<UpdateResourcesEditor cid="ctr_1" currentMemLimit="2g" currentCpus={1} onDone={onDone} />);

  const mem = screen.getByLabelText(/memory/i) as HTMLInputElement;
  const cpu = screen.getByLabelText(/cpu/i) as HTMLInputElement;
  expect(mem.value).toBe("2g");
  expect(cpu.value).toBe("1");

  fireEvent.change(mem, { target: { value: "3g" } });
  fireEvent.change(cpu, { target: { value: "1.5" } });
  fireEvent.click(screen.getByRole("button", { name: /^update$/i }));

  await waitFor(() =>
    expect(mutateAsync).toHaveBeenCalledWith({ mem_limit: "3g", cpus: 1.5 }),
  );
  await waitFor(() => expect(onDone).toHaveBeenCalled());
});

test("cancel collapses without submitting", () => {
  const onDone = vi.fn();
  render(<UpdateResourcesEditor cid="ctr_1" currentMemLimit="2g" currentCpus={1} onDone={onDone} />);
  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onDone).toHaveBeenCalled();
  expect(mutateAsync).not.toHaveBeenCalled();
});
