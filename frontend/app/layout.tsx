import type { Metadata } from "next"
import { Geist, Geist_Mono } from "next/font/google"
import "./globals.css"
import { Sidebar } from "@/components/Sidebar"
import { CommandPalette } from "@/components/CommandPalette"
import { Toaster } from "@/components/ui/toast"

const geist = Geist({ subsets: ["latin"], variable: "--font-geist" })
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono" })

export const metadata: Metadata = {
  title: "currobot",
  description: "Local job search automation",
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className="dark">
      <body className={`${geist.variable} ${geistMono.variable} bg-[#1C1C1E] text-white antialiased`}>
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
