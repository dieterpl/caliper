// Render an .svg file's text as a picture. It goes through a data-URL <img>,
// never inline into the DOM, so nothing in a file's SVG (script, foreignObject)
// can run inside the app. The checkered backdrop reads as "this is an image".

export default function SvgPreview({ text }: { text: string }) {
  const src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(text);
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
        alt="SVG preview"
        className="max-h-full max-w-full object-contain drop-shadow"
        style={{ imageRendering: "auto" }}
      />
    </div>
  );
}
