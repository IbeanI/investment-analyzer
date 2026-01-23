"use client";

import { useState, useEffect, useCallback } from "react";

export type NotificationType = "success" | "error" | "warning" | "info";

export interface Notification {
  id: string;
  type: NotificationType;
  title: string;
  message?: string;
  timestamp: number;
  read: boolean;
}

const STORAGE_KEY = "portfolio-notifications";
const MAX_NOTIFICATIONS = 50;

function getStoredNotifications(): Notification[] {
  if (typeof window === "undefined") return [];
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch {
    return [];
  }
}

function saveNotifications(notifications: Notification[]) {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications));
  } catch {
    // Storage full or unavailable
  }
}

export function useNotifications() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load notifications from localStorage on mount
  useEffect(() => {
    setNotifications(getStoredNotifications());
    setIsLoaded(true);
  }, []);

  // Save to localStorage whenever notifications change
  useEffect(() => {
    if (isLoaded) {
      saveNotifications(notifications);
    }
  }, [notifications, isLoaded]);

  const addNotification = useCallback(
    (type: NotificationType, title: string, message?: string) => {
      const newNotification: Notification = {
        id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        type,
        title,
        message,
        timestamp: Date.now(),
        read: false,
      };

      setNotifications((prev) => {
        const updated = [newNotification, ...prev].slice(0, MAX_NOTIFICATIONS);
        return updated;
      });

      return newNotification.id;
    },
    []
  );

  const markAsRead = useCallback((id: string) => {
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  }, []);

  const markAllAsRead = useCallback(() => {
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }, []);

  const removeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }, []);

  const clearAll = useCallback(() => {
    setNotifications([]);
  }, []);

  const unreadCount = notifications.filter((n) => !n.read).length;

  return {
    notifications,
    unreadCount,
    addNotification,
    markAsRead,
    markAllAsRead,
    removeNotification,
    clearAll,
    isLoaded,
  };
}

// Singleton for global access (used by toast wrapper)
let globalAddNotification: ((type: NotificationType, title: string, message?: string) => string) | null = null;

export function setGlobalNotificationHandler(
  handler: (type: NotificationType, title: string, message?: string) => string
) {
  globalAddNotification = handler;
}

export function addGlobalNotification(
  type: NotificationType,
  title: string,
  message?: string
): string | null {
  if (globalAddNotification) {
    return globalAddNotification(type, title, message);
  }
  return null;
}
