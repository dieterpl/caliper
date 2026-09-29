export type Kind = "component" | "assembly" | "scene";
export type Values = Record<string, unknown>;
export interface Instance { name: string; component?: string; assembly?: string; project?: string; scene?: string; kind?: Kind; origin?: number[]; rotation?: number[]; config?: Values }
export interface Joint { name?: string; type: string; a: string; b: string; anchor: number[]; axis?: number[]; limits?: number[]; motor?: Values }
export interface Interface { body: string; anchor: number[]; axis: number[] }
export interface Definition { label?: string; builder?: string; hardware?: string; legacy_part?: string; source?: string; group?: string; parameters?: Values; config?: Values; instances?: Instance[]; assembly?: string; overrides?: Record<string, Partial<Instance>>; joints?: Joint[]; interfaces?: Record<string, Interface>; settings?: Values; environment?: { ground?: boolean; size?: number } }
export interface Manifest { version: number; parameters?: Values; default_scene: string; active_scene?: string; components: Record<string, Definition | string>; assemblies: Record<string, Definition | string>; scenes: Record<string, Definition | string> }
export interface ProjectState { name: string; project: string; initialized: boolean; revision: string; manifest: Manifest; git: { branch: string; commit: string; changes: string[] }; dependencies: { name: string; path: string; commit: string; pinned: string; dirty: boolean; present: boolean; scenes: Record<string, Definition | string> }[]; hardware: { id: string; mass: number }[]; sources: string[]; available_projects: string[]; preview?: string; created?: string }
export const keyFor = (kind: Kind) => ({ component: "components", assembly: "assemblies", scene: "scenes" } as const)[kind];
export const asDefinition = (value: Definition | string): Definition => typeof value === "string" ? { builder: value } : value;
export const makeId = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 50);
