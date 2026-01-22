"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  getUserSettings,
  updateUserSettings,
  getUserProfile,
  updateUserProfile,
  changePassword,
  deleteAccount,
} from "@/lib/api/users";
import { clearTokens } from "@/lib/api/client";
import type {
  UserSettingsUpdate,
  UserProfileUpdate,
  PasswordChangeRequest,
  AccountDeleteRequest,
} from "@/types/api";
import { toast } from "sonner";
import { useRouter } from "next/navigation";

// -----------------------------------------------------------------------------
// Query Keys
// -----------------------------------------------------------------------------

export const userKeys = {
  all: ["user"] as const,
  settings: () => [...userKeys.all, "settings"] as const,
  profile: () => [...userKeys.all, "profile"] as const,
};

// -----------------------------------------------------------------------------
// Settings Queries & Mutations
// -----------------------------------------------------------------------------

/**
 * Hook to fetch user settings
 */
export function useUserSettings() {
  return useQuery({
    queryKey: userKeys.settings(),
    queryFn: () => getUserSettings(),
  });
}

/**
 * Hook to update user settings
 */
export function useUpdateUserSettings() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: UserSettingsUpdate) => updateUserSettings(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.settings() });
      toast.success("Settings saved");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to save settings");
    },
  });
}

// -----------------------------------------------------------------------------
// Profile Queries & Mutations
// -----------------------------------------------------------------------------

/**
 * Hook to fetch user profile
 */
export function useUserProfile() {
  return useQuery({
    queryKey: userKeys.profile(),
    queryFn: () => getUserProfile(),
  });
}

/**
 * Hook to update user profile
 */
export function useUpdateUserProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: UserProfileUpdate) => updateUserProfile(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: userKeys.profile() });
      toast.success("Profile updated");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update profile");
    },
  });
}

// -----------------------------------------------------------------------------
// Password & Account Mutations
// -----------------------------------------------------------------------------

/**
 * Hook to change password
 */
export function useChangePassword() {
  return useMutation({
    mutationFn: (data: PasswordChangeRequest) => changePassword(data),
    onSuccess: () => {
      toast.success("Password changed successfully");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to change password");
    },
  });
}

/**
 * Hook to delete account
 */
export function useDeleteAccount() {
  const router = useRouter();

  return useMutation({
    mutationFn: (data: AccountDeleteRequest) => deleteAccount(data),
    onSuccess: () => {
      clearTokens();
      toast.success("Account deleted");
      router.push("/login");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete account");
    },
  });
}
