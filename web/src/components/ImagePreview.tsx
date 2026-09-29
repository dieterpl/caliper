// Render an image file as a picture. The bytes come from the workspace's
// /file route (an <img> can't read the daemon's text response), so this is just
// the frame: the same checkered backdrop as SvgPreview, so it reads as an image.

export default function ImagePreview({ src }: { src: string }) {
  return (
    <div
      className="flex h-full w-full items-center justify-center overflow-auto p-4"
      style={{
        backgroundColor: "hsl(var(--muted))",
        backgroundImage:
          "linear-gradient(45deg, hsl(var(--border)) 25%, transparent 25%)," +
          "linear-gradient(-45deg, hsl(var(--border)) 25%, transparent 25%)," +
          "linear-gradient(45deg, transparent 75%, hsl(var(--border)) 75%)," +
          "linear-gradient(-45deg, transparent 75%, hsl(var(--border)) 75%)",
        backgroundSize: "16px 16px",
        backgroundPosition: "0 0, 0 8px, 8px -8px, -8px 0",
      }}
    >
      <img
        src={src}
        alt="image preview"
        className="max-h-full max-w-full object-contain drop-shadow"
        style={{ imageRendering: "auto" }}
      />
    </div>
  );
}
