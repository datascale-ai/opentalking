import { ArrowRight } from "lucide-react";
import { architectureNodes } from "../content";

export function ArchitectureFlow() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-panel">
      <div className="grid gap-3 lg:grid-cols-5">
        {architectureNodes.map((node, index) => (
          <div key={node.label} className="relative rounded-lg bg-slate-50 p-4">
            <p className="code-font text-xs font-semibold uppercase tracking-[0.16em] text-cyanline">
              {node.label}
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-600">{node.description}</p>
            {index < architectureNodes.length - 1 ? (
              <ArrowRight className="absolute -right-5 top-1/2 z-10 hidden h-5 w-5 -translate-y-1/2 text-slate-300 lg:block" />
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}
