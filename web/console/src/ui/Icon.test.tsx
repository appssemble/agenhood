import { render } from "@testing-library/react";
import { Icons } from "./Icon";
test("renders icons as 24-viewBox svgs", () => {
  const { container } = render(<><Icons.Dashboard /><Icons.Send /><Icons.Pin /></>);
  const svgs = container.querySelectorAll("svg");
  expect(svgs.length).toBe(3);
  expect(svgs[0].getAttribute("viewBox")).toBe("0 0 24 24");
});
