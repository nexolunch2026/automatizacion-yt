import { SystemStatus } from "./status";

export default function Home() {
  return (
    <main style={{ maxWidth: 640, margin: "64px auto", padding: "0 16px" }}>
      <h1 style={{ marginBottom: 4 }}>Faceless Studio</h1>
      <p style={{ color: "var(--muted)", marginTop: 0 }}>
        Estado del sistema. El dashboard llega en el siguiente milestone.
      </p>
      <SystemStatus />
    </main>
  );
}
