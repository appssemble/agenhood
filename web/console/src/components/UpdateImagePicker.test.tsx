import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import { UpdateImagePicker } from "./UpdateImagePicker";

const mutateAsync = vi.fn().mockResolvedValue({ id: "ctr_1", status: "running", image_tag: "v2" });

vi.mock("../api/queries", () => ({
  useImageTags: () => ({
    data: {
      tags: [
        { tag: "v2", source: "registry" },
        { tag: "v1", source: "registry" },
        { tag: "dev", source: "local" },
      ],
      default_tag: "dev",
      registry_unavailable: false,
    },
    isLoading: false,
  }),
  useUpdateImage: () => ({ mutateAsync, isPending: false }),
}));

vi.mock("./Toast", () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}));

beforeEach(() => mutateAsync.mockClear());

test("preselects the current tag and submits the chosen tag", async () => {
  const onDone = vi.fn();
  render(<UpdateImagePicker cid="ctr_1" currentTag="v1" onDone={onDone} />);

  const select = screen.getByLabelText(/image tag/i) as HTMLSelectElement;
  expect(select.value).toBe("v1");

  fireEvent.change(select, { target: { value: "v2" } });
  fireEvent.click(screen.getByRole("button", { name: /^update$/i }));

  await waitFor(() => expect(mutateAsync).toHaveBeenCalledWith("v2"));
  await waitFor(() => expect(onDone).toHaveBeenCalled());
});

test("custom option reveals a free-form field", () => {
  render(<UpdateImagePicker cid="ctr_1" currentTag="v1" onDone={() => {}} />);
  fireEvent.change(screen.getByLabelText(/image tag/i), { target: { value: "__custom__" } });
  expect(screen.getByPlaceholderText(/e\.g\. dev-myfeature/i)).toBeInTheDocument();
});

test("blank custom tag does not submit", () => {
  render(<UpdateImagePicker cid="ctr_1" currentTag="v1" onDone={() => {}} />);
  fireEvent.change(screen.getByLabelText(/image tag/i), { target: { value: "__custom__" } });
  fireEvent.click(screen.getByRole("button", { name: /^update$/i }));
  expect(mutateAsync).not.toHaveBeenCalled();
});

test("cancel collapses without submitting", () => {
  const onDone = vi.fn();
  render(<UpdateImagePicker cid="ctr_1" currentTag="v1" onDone={onDone} />);
  fireEvent.click(screen.getByRole("button", { name: /cancel/i }));
  expect(onDone).toHaveBeenCalled();
  expect(mutateAsync).not.toHaveBeenCalled();
});
