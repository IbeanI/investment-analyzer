"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  useCallback,
  type ReactNode,
} from "react";
import { useRouter, usePathname } from "next/navigation";
import type { User } from "@/types/api";
import {
  getCurrentUser,
  login as loginApi,
  logout as logoutApi,
  register as registerApi,
  getGoogleAuthUrl,
} from "@/lib/api/auth";
import { getAccessToken, clearTokens } from "@/lib/api/client";
import type { UserLoginRequest, UserRegisterRequest } from "@/types/api";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

interface AuthContextValue {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (data: UserLoginRequest) => Promise<void>;
  register: (data: UserRegisterRequest) => Promise<void>;
  logout: () => Promise<void>;
  loginWithGoogle: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

// -----------------------------------------------------------------------------
// Context
// -----------------------------------------------------------------------------

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// Public routes that don't require authentication
const PUBLIC_ROUTES = [
  "/login",
  "/register",
  "/verify-email",
  "/reset-password",
  "/forgot-password",
];

// -----------------------------------------------------------------------------
// Provider Component
// -----------------------------------------------------------------------------

interface AuthProviderProps {
  children: ReactNode;
}

export function AuthProvider({ children }: AuthProviderProps) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();

  const isAuthenticated = !!user;

  // Fetch current user on mount
  const fetchUser = useCallback(async () => {
    const token = getAccessToken();
    if (!token) {
      setUser(null);
      setIsLoading(false);
      return;
    }

    try {
      const userData = await getCurrentUser();
      setUser(userData);
    } catch {
      // Token might be invalid, clear it
      clearTokens();
      setUser(null);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchUser();
  }, [fetchUser]);

  // Redirect logic
  useEffect(() => {
    if (isLoading) return;

    const isPublicRoute = PUBLIC_ROUTES.some((route) =>
      pathname.startsWith(route)
    );

    if (!isAuthenticated && !isPublicRoute) {
      // Not authenticated and trying to access protected route
      router.push("/login");
    } else if (isAuthenticated && isPublicRoute) {
      // Authenticated but on public route (e.g., login page)
      router.push("/");
    }
  }, [isAuthenticated, isLoading, pathname, router]);

  // Login handler
  const login = useCallback(
    async (data: UserLoginRequest) => {
      await loginApi(data);
      const userData = await getCurrentUser();
      setUser(userData);
      router.push("/");
    },
    [router]
  );

  // Register handler
  const register = useCallback(async (data: UserRegisterRequest) => {
    await registerApi(data);
    // After registration, user needs to verify email
    // Don't set user here, redirect to verify email message
  }, []);

  // Logout handler
  const logout = useCallback(async () => {
    await logoutApi();
    setUser(null);
    router.push("/login");
  }, [router]);

  // Google OAuth handler
  const loginWithGoogle = useCallback(async () => {
    const { authorization_url } = await getGoogleAuthUrl();
    window.location.href = authorization_url;
  }, []);

  // Refresh user data
  const refreshUser = useCallback(async () => {
    try {
      const userData = await getCurrentUser();
      setUser(userData);
    } catch {
      // Ignore errors
    }
  }, []);

  const value: AuthContextValue = {
    user,
    isLoading,
    isAuthenticated,
    login,
    register,
    logout,
    loginWithGoogle,
    refreshUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// -----------------------------------------------------------------------------
// Hook
// -----------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
