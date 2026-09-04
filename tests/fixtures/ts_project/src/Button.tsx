import { greet } from "./foo";

export function Button() {
  return <button>{greet("hi")}</button>;
}
