import { Play, Pause, RotateCcw, LoaderCircle } from "lucide-react";
import { useViewer } from "@/hooks/useViewer";
import Viewport from "@/components/Viewport";
import { Button } from "@/components/ui/button";
import { Logo } from "@/components/Logo";
import type { Scene } from "@/lib/types";
import { useEffect } from "react";
export default function ProjectPreview({ slug, directory, focus, onScene }: { slug: string; directory: string; focus?: string; onScene: (scene: Scene | null) => void }) {
  const v = useViewer(slug, directory, focus);
  useEffect(() => { onScene(v.scene); }, [v.scene, onScene]);
  const loading = /^(initializing|fetching scene|loading model)/.test(v.status);
  const failed = !loading && (!v.scene || v.status.startsWith("error:"));
  return <div className="relative h-full" aria-busy={loading}>
    <Viewport v={v} />
    {(loading || failed) && <div className="absolute inset-x-0 top-0 bottom-8 flex flex-col items-center justify-center gap-3 bg-background/90 px-8 text-center" role="status" aria-live="polite">
      <Logo size={44} mono className="text-muted-foreground opacity-20" />
      <h2 className="flex items-center gap-2 text-sm font-medium">{loading ? <><LoaderCircle size={15} className="animate-spin" />Loading 3D preview</> : "Preview unavailable"}</h2>
      <p className="max-w-md text-xs leading-5 text-muted-foreground">{loading ? "Opening the prepared model. You can keep browsing while it loads." : v.status}</p>
      {failed && <Button size="xs" variant="outline" onClick={v.reload}><RotateCcw /> Try again</Button>}
    </div>}
    {v.hasJoints && <div className="absolute bottom-11 left-3 flex gap-1"><Button size="xs" variant="secondary" onClick={v.play} title={v.running ? "Pause the simulation" : "Run the joints in this scene"}>{v.running ? <Pause /> : <Play />} {v.running ? "Pause" : "Simulate"}</Button><Button size="xs" variant="outline" onClick={v.reset}><RotateCcw /> Reset</Button></div>}
  </div>;
}
