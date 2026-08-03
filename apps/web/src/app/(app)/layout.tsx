import { AppNav } from "@/components/layout/app-nav";
import { AuthGate } from "@/components/layout/auth-gate";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="min-h-screen bg-[radial-gradient(ellipse_at_top,_hsl(199_70%_92%/_0.35),_transparent_50%)] dark:bg-[radial-gradient(ellipse_at_top,_hsl(199_40%_18%/_0.25),_transparent_50%)]">
        <AppNav />
        <main className="mx-auto max-w-6xl px-4 py-6 pb-16">{children}</main>
      </div>
    </AuthGate>
  );
}
