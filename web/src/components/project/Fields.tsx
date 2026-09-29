import type { Values } from "./types";
export const inputClass = "w-full rounded border bg-background px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-ring";
export function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block space-y-1.5"><span className="text-xs text-muted-foreground">{label}</span>{children}</label>;
}
export function Triple({ label, value = [0, 0, 0], onChange }: { label: string; value?: number[]; onChange: (v: number[]) => void }) {
  return <Field label={label}><div className="grid grid-cols-3 gap-1">{["X", "Y", "Z"].map((axis, i) => <label key={axis} className="flex items-center gap-1 rounded border px-1 text-[10px] text-muted-foreground">{axis}<input aria-label={`${label} ${axis}`} type="number" step="any" className="min-w-0 w-full bg-transparent py-1.5 text-xs text-foreground outline-none" value={value[i]} onChange={e => onChange(value.map((v, j) => j === i ? Number(e.target.value) : v))} /></label>)}</div></Field>;
}
export function ParameterFields({ values, onChange }: { values: Values; onChange: (v: Values) => void }) {
  return <div className="space-y-3">{Object.entries(values).map(([name, value]) => <Field key={name} label={name.replaceAll("_", " ")}>{typeof value === "boolean" ? <input aria-label={name} type="checkbox" checked={value} onChange={e => onChange({ ...values, [name]: e.target.checked })} /> : typeof value === "number" ? <input aria-label={name} className={inputClass} type="number" step="any" value={value} onChange={e => onChange({ ...values, [name]: Number(e.target.value) })} /> : typeof value === "string" ? <input aria-label={name} className={inputClass} value={value} onChange={e => onChange({ ...values, [name]: e.target.value })} /> : <textarea aria-label={name} className={inputClass} defaultValue={JSON.stringify(value)} onBlur={e => { try { onChange({ ...values, [name]: JSON.parse(e.target.value) }); } catch { e.target.setCustomValidity("Enter valid JSON"); e.target.reportValidity(); } }} />}</Field>)}</div>;
}
