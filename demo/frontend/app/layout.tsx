import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Macaw OpenVoice — Voice Runtime",
  description: "STT + TTS in a single server. OpenAI-compatible API, WebSocket streaming, smart VAD.",
  icons: { icon: "/img/logo-192.png", apple: "/img/logo-256.png" },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR" className="dark" suppressHydrationWarning>
      <body className="antialiased">{children}</body>
    </html>
  );
}
