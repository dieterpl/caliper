import ReactDOM from "react-dom/client";
import "./index.css";
import App from "./App";

// No StrictMode: it double-mounts effects in dev, which would tear down and
// rebuild the WebGL context on every load. Production behaviour is identical.
ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <App />,
);
