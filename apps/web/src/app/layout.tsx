import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Faceless Studio",
  description: "Productora de YouTube impulsada por IA",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
