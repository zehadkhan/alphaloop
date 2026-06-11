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
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Runs before React hydrates — prevents flash of wrong theme */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{var t=localStorage.getItem('alphaloop-theme');document.documentElement.classList.toggle('dark',t!=='light')}catch(e){document.documentElement.classList.add('dark')}})()`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
