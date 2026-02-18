import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import { Sidebar } from "@/components/Sidebar"
import { CommandPalette } from "@/components/CommandPalette"
import { Toaster } from "@/components/ui/toast"
import { SetupGuard } from "@/components/SetupGuard"

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" })
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" })

export const metadata: Metadata = {
  title: "currobot",
  description: "Local job search automation",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <body className={`${geist.variable} ${geistMono.variable} antialiased`} style={{ background: "var(--bg)", color: "var(--fg)" }}>
        <SetupGuard />
        <Sidebar />
        <CommandPalette />
        <Toaster />
        <main className="ml-16 min-h-screen p-6">
          {children}
        </main>
      </body>
    </html>
  )
}
