"use client";

import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/providers/auth-provider";
import {
  AUTO_SESSION_EVENT,
  COACH_SETTINGS_EVENT,
  type CoachSettings,
  applyServerCoachPrefs,
  loadAutoSession,
  loadCoachSettings,
  normalizeCoachSettings,
  saveAutoSession,
  saveCoachSettings,
} from "@/lib/coach-settings";
import { api } from "@/lib/api";

export function useCoachSettings() {
  const { user, isAuthenticated } = useAuth();
  const userId = user?.id ?? null;
  const [settings, setSettings] = useState<CoachSettings>(() => loadCoachSettings(userId));

  useEffect(() => {
    const sync = () => setSettings(loadCoachSettings(userId));
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<CoachSettings>).detail;
      if (detail) setSettings(detail);
      else sync();
    };
    window.addEventListener("storage", sync);
    window.addEventListener(COACH_SETTINGS_EVENT, onCustom);
    sync();
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener(COACH_SETTINGS_EVENT, onCustom);
    };
  }, [userId]);

  useEffect(() => {
    if (!isAuthenticated || userId == null) return;
    let cancelled = false;
    void (async () => {
      try {
        const prefs = await api.coachSettings();
        if (cancelled) return;
        const next = applyServerCoachPrefs(
          prefs.settings as Partial<CoachSettings>,
          prefs.auto_session_enabled,
          userId,
        );
        setSettings(next);
      } catch {
        // Keep local cache if the prefs endpoint is temporarily unavailable.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, userId]);

  const update = useCallback(
    (partial: Partial<Omit<CoachSettings, "entrySignal">>) => {
      const next = saveCoachSettings(partial, userId);
      setSettings(next);
      if (isAuthenticated) {
        void api
          .updateCoachSettings({ settings: next })
          .then((prefs) => {
            applyServerCoachPrefs(
              prefs.settings as Partial<CoachSettings>,
              prefs.auto_session_enabled,
              userId as number,
            );
          })
          .catch(() => {
            /* local cache already updated */
          });
      }
      return next;
    },
    [isAuthenticated, userId],
  );

  return { settings, update, setAll: update, userId };
}

/** AUTO on/off shared across Market + Coach tabs for the browser session. */
export function useAutoSession() {
  const { user, isAuthenticated } = useAuth();
  const userId = user?.id ?? null;
  const { settings } = useCoachSettings();
  const [autoEnabled, setAutoEnabledState] = useState(() =>
    loadAutoSession(settings.autoOnDefault, userId),
  );

  useEffect(() => {
    const sync = () => setAutoEnabledState(loadAutoSession(settings.autoOnDefault, userId));
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<boolean>).detail;
      if (typeof detail === "boolean") setAutoEnabledState(detail);
      else sync();
    };
    const onStorage = (e: StorageEvent) => {
      if (
        e.key === null ||
        e.key === "pcc_auto_session" ||
        e.key?.startsWith("pcc_auto_session:") ||
        e.key === "pcc_coach_settings" ||
        e.key?.startsWith("pcc_coach_settings:")
      ) {
        sync();
      }
    };
    window.addEventListener(AUTO_SESSION_EVENT, onCustom);
    window.addEventListener("storage", onStorage);
    sync();
    return () => {
      window.removeEventListener(AUTO_SESSION_EVENT, onCustom);
      window.removeEventListener("storage", onStorage);
    };
  }, [settings.autoOnDefault, userId]);

  const setAutoEnabled = useCallback(
    (next: boolean | ((prev: boolean) => boolean)) => {
      setAutoEnabledState((prev) => {
        const value = typeof next === "function" ? next(prev) : next;
        saveAutoSession(value, userId);
        if (isAuthenticated) {
          void api
            .updateCoachSettings({
              settings: normalizeCoachSettings(loadCoachSettings(userId)),
              auto_session_enabled: value,
            })
            .catch(() => {
              /* local cache already updated */
            });
        }
        return value;
      });
    },
    [isAuthenticated, userId],
  );

  return { autoEnabled, setAutoEnabled };
}
