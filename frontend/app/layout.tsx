import type { Metadata } from "next";
import { AuthProvider } from "@/lib/auth";
import { THEME_INIT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "SmartRoute",
  description: "SmartRoute",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT }} />
      </head>
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
