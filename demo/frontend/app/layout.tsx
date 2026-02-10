import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Macaw OpenVoice Demo",
  description: "Dashboard interativo do scheduler Macaw",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body>{children}</body>
    </html>
  );
}
