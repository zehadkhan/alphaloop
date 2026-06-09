import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "AlphaLoop — Trading Dashboard",
  description: "Autonomous BNB/USDT trading agent dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
