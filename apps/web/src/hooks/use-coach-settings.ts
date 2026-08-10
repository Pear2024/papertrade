"use client";

import { useCallback, useEffect, useState } from "react";

import {
  AUTO_SESSION_EVENT,
  COACH_SETTINGS_EVENT,
  type CoachSettings,
  loadAutoSession,
  loadCoachSettings,
  saveAutoSession,
  saveCoachSettings,
} from "@/lib/coach-settings";

export function useCoachSettings() {
  const [settings, setSettings] = useState<CoachSettings>(() => loadCoachSettings());

  useEffect(() => {
    const sync = () => setSettings(loadCoachSettings());
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
  }, []);

  const update = useCallback((partial: Partial<Omit<CoachSettings, "entrySignal">>) => {
    const next = saveCoachSettings(partial);
    setSettings(next);
    return next;
  }, []);

  return { settings, update, setAll: update };
}

/** AUTO on/off shared across Market + Coach tabs for the browser session. */
export function useAutoSession() {
  const { settings } = useCoachSettings();
  const [autoEnabled, setAutoEnabledState] = useState(() =>
    loadAutoSession(settings.autoOnDefault),
  );

  useEffect(() => {
    const sync = () => setAutoEnabledState(loadAutoSession(settings.autoOnDefault));
    const onCustom = (e: Event) => {
      const detail = (e as CustomEvent<boolean>).detail;
      if (typeof detail === "boolean") setAutoEnabledState(detail);
      else sync();
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === null || e.key === "pcc_auto_session" || e.key === "pcc_coach_settings") {
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
  }, [settings.autoOnDefault]);

  const setAutoEnabled = useCallback((next: boolean | ((prev: boolean) => boolean)) => {
    setAutoEnabledState((prev) => {
      const value = typeof next === "function" ? next(prev) : next;
      saveAutoSession(value);
      return value;
    });
  }, []);

  return { autoEnabled, setAutoEnabled };
}
