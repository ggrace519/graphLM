import { greet } from "./foo";

export function helper(name: string): string {
  return name.toUpperCase();
}

export function ping(): string {
  return greet("bar");
}
