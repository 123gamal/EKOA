"use client";

import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { notificationApi, type Notification } from "@/lib/api";
import { cn } from "@/lib/utils";

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const [unreadCount, setUnreadCount] = useState(0);
  const [items, setItems] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const count = await notificationApi.unreadCount();
        if (!cancelled) setUnreadCount(count);
      } catch {
        // Silently skip — a failed poll shouldn't disrupt the rest of the UI.
      }
    }
    poll();
    const interval = setInterval(poll, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  async function togglePanel() {
    const next = !open;
    setOpen(next);
    if (next) {
      setLoading(true);
      try {
        const page = await notificationApi.list(false, 1, 10);
        setItems(page.items);
      } catch {
        setItems([]);
      } finally {
        setLoading(false);
      }
    }
  }

  async function handleMarkRead(notification: Notification) {
    if (notification.read_at) return;
    try {
      const updated = await notificationApi.markRead(notification.id);
      setItems((prev) => prev.map((n) => (n.id === updated.id ? updated : n)));
      setUnreadCount((prev) => Math.max(0, prev - 1));
    } catch {
      // Non-critical — leave the item unread on failure.
    }
  }

  return (
    <div className="relative" ref={containerRef}>
      <button
        className="relative p-2 rounded-lg hover:bg-[var(--muted)]"
        onClick={togglePanel}
        aria-label="Notifications"
      >
        <Bell className="h-5 w-5" />
        {unreadCount > 0 && (
          <span className="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-[var(--destructive)] px-1 text-[10px] font-semibold text-white">
            {unreadCount > 99 ? "99+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 rounded-lg border border-[var(--border)] bg-[var(--card)] shadow-lg">
          <div className="border-b border-[var(--border)] px-4 py-3 text-sm font-semibold">
            Notifications
          </div>
          <div className="max-h-96 overflow-auto">
            {loading && (
              <div className="px-4 py-6 text-center text-sm text-[var(--muted-foreground)]">
                Loading…
              </div>
            )}
            {!loading && items.length === 0 && (
              <div className="px-4 py-6 text-center text-sm text-[var(--muted-foreground)]">
                No notifications
              </div>
            )}
            {!loading &&
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleMarkRead(n)}
                  className={cn(
                    "block w-full border-b border-[var(--border)] px-4 py-3 text-left text-sm last:border-b-0 hover:bg-[var(--muted)]",
                    !n.read_at && "bg-[var(--primary)]/5"
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <p className="font-medium">{n.title}</p>
                    {!n.read_at && (
                      <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-[var(--primary)]" />
                    )}
                  </div>
                  {n.body && (
                    <p className="mt-1 text-xs text-[var(--muted-foreground)] line-clamp-2">
                      {n.body}
                    </p>
                  )}
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
