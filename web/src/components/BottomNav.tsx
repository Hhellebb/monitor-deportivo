"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, CalendarDays, CheckCircle2 } from "lucide-react";

const TABS = [
  { href: "/", label: "Hoy", icon: CalendarDays },
  { href: "/resultados", label: "Resultados", icon: CheckCircle2 },
  { href: "/resumen", label: "Resumen", icon: BarChart3 },
] as const;

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Navegación principal"
      className="fixed bottom-0 left-0 right-0 z-50 border-t border-slate-200 bg-white/95 backdrop-blur-md"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <div className="mx-auto grid max-w-md grid-cols-3">
        {TABS.map(({ href, label, icon: Icon }) => {
          const isActive =
            href === "/" ? pathname === "/" : pathname.startsWith(href);

          return (
            <Link
              key={href}
              href={href}
              className={`flex min-h-[60px] flex-col items-center justify-center gap-1 px-2 py-2 text-xs font-semibold transition-colors ${
                isActive
                  ? "text-[#0969DA]"
                  : "text-slate-500 active:bg-slate-100 hover:text-slate-800"
              }`}
            >
              <span
                className={`flex h-7 w-12 items-center justify-center rounded-full transition-colors ${
                  isActive ? "bg-blue-50" : ""
                }`}
              >
                <Icon className="h-5 w-5" strokeWidth={isActive ? 2.4 : 2} />
              </span>
              <span>{label}</span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
