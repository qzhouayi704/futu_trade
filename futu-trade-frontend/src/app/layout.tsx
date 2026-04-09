import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { AppLayout } from "@/components/layout";

export const metadata: Metadata = {
  title: "富途量化交易系统",
  description: "基于 Next.js 15.4 + React 19 的量化交易前端",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <AppLayout>{children}</AppLayout>
        </Providers>
      </body>
    </html>
  );
}
