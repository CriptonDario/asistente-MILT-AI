import { useId } from "react";
import { cn } from "../../lib/cn";

interface LogoProps {
  size?: number;
  /** Animación de "respiración" mientras el modelo genera. */
  active?: boolean;
  className?: string;
}

/** Monograma MILT: tres trazos (local, web, memoria) que convergen en un nodo central. */
export function Logo({ size = 28, active = false, className }: LogoProps) {
  const gradientId = useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={cn(active && "logo-breathe", className)}
    >
      <defs>
        <linearGradient id={gradientId} x1="4" y1="4" x2="28" y2="28" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#3B82F6" />
          <stop offset=".55" stopColor="#8B5CF6" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
      </defs>
      <path
        d="M7 25V8l9 10 9-10v17M16 18v6"
        stroke={`url(#${gradientId})`}
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="18" r="2.6" fill="#22D3EE" />
    </svg>
  );
}
