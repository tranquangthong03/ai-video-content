import type { ReactNode } from "react";
import "./globals.css";

export const metadata = { title: "Short Video AI", description: "Từ địa chỉ website thành video marketing dọc" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="vi">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&display=swap"
        />
      </head>
      <body>
        <header className="border-b border-border bg-card">
          <div className="mx-auto flex h-14 max-w-6xl items-center px-4">
            <a href="/" className="text-base font-bold tracking-tight">
              Short Video <span className="text-primary">AI</span>
            </a>
            <span className="ml-3 hidden text-sm text-muted-foreground sm:inline">
              Từ địa chỉ website thành video dọc 9:16
            </span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
