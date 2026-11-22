import { type ClassValue, clsx } from "clsx";

/** Combina clases condicionales. */
export function cn(...values: ClassValue[]): string {
  return clsx(values);
}
