import { extractVariables, resolve } from "./prompts";

test("extractVariables returns ordered, de-duplicated names", () => {
  expect(extractVariables("Hi {{team}}, week of {{ date }}. {{team}} again")).toEqual(["team", "date"]);
});

test("extractVariables ignores malformed braces", () => {
  expect(extractVariables("none { {x}} {{}} {{1a-b}}")).toEqual([]);
});

test("resolve substitutes provided values", () => {
  expect(resolve("Hi {{team}} on {{date}}", { team: "Platform", date: "Mon" }))
    .toBe("Hi Platform on Mon");
});

test("resolve leaves unfilled variables intact", () => {
  expect(resolve("Hi {{team}} on {{date}}", { team: "Platform" }))
    .toBe("Hi Platform on {{date}}");
});

test("resolve handles inner whitespace", () => {
  expect(resolve("Hi {{ team }}", { team: "X" })).toBe("Hi X");
});
