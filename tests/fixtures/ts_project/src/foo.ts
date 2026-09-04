import { helper } from "./bar";
import React from "react";

export function greet(name: string): string {
  return helper(name);
}
