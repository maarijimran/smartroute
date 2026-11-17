"use client";

import { useRouter } from "next/navigation";
import { Suspense, useEffect } from "react";
import { Sidebar } from "@/components/sidebar";
import { Spinner } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { ChatsProvider } from "@/lib/chats";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (loading || !user) return <Spinner />;

  return (
    <ChatsProvider>
      <div className="flex h-screen bg-slate-50">
        <Suspense fallback={<div className="w-[52px] shrink-0 bg-sidebar" />}>
          <Sidebar />
        </Suspense>
        <main className="relative min-w-0 flex-1 overflow-hidden">{children}</main>
      </div>
    </ChatsProvider>
  );
}
