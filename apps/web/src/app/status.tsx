"use client";

import { useEffect, useState } from "react";

type Health = {
  ok: boolean;
  services: Record<string, { ok: boolean; error?: string }>;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const LABELS: Record<string, string> = {
  database: "Base de datos",
  redis: "Cola (Redis)",
  storage: "Almacenamiento",
  worker: "Worker",
};

export function SystemStatus() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setError("No se puede conectar con la API"));
  }, []);

  if (error) return <p style={{ color: "var(--bad)" }}>{error}</p>;
  if (!health) return <p style={{ color: "var(--muted)" }}>Comprobando servicios…</p>;

  return (
    <ul style={{ listStyle: "none", padding: 0, display: "grid", gap: 8 }}>
      {Object.entries(health.services).map(([name, s]) => (
        <li
          key={name}
          title={s.error}
          style={{ background: "var(--panel)", padding: "12px 16px", borderRadius: 8 }}
        >
          <span style={{ color: s.ok ? "var(--ok)" : "var(--bad)" }}>{s.ok ? "●" : "○"}</span>{" "}
          {LABELS[name] ?? name}
          {!s.ok && <span style={{ color: "var(--muted)" }}> — {s.error}</span>}
        </li>
      ))}
    </ul>
  );
}
