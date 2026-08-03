"use client";

import { useCallback, useEffect, useState } from "react";

import {
  COACH_SETTINGS_EVENT,
  type CoachSettings,
  loadCoachSettings,
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

  const update = useCallback((partial: Partial<CoachSettings>) => {
    const next = saveCoachSettings(partial);
    setSettings(next);
    return next;
  }, []);

  return { settings, update, setAll: update };
}
