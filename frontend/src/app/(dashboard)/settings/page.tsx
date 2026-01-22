"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Loader2, User, Settings, Shield, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Separator } from "@/components/ui/separator";
import { Label } from "@/components/ui/label";
import {
  useUserSettings,
  useUpdateUserSettings,
  useUserProfile,
  useUpdateUserProfile,
  useChangePassword,
  useDeleteAccount,
} from "@/hooks/use-user-settings";
import type { Theme, DateFormat, NumberFormat } from "@/types/api";

// -----------------------------------------------------------------------------
// Constants
// -----------------------------------------------------------------------------

const THEMES: { value: Theme; label: string }[] = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

const DATE_FORMATS: { value: DateFormat; label: string; example: string }[] = [
  { value: "YYYY-MM-DD", label: "ISO", example: "2026-01-22" },
  { value: "MM/DD/YYYY", label: "US", example: "01/22/2026" },
  { value: "DD/MM/YYYY", label: "EU", example: "22/01/2026" },
];

const NUMBER_FORMATS: { value: NumberFormat; label: string; example: string }[] = [
  { value: "US", label: "US", example: "1,234.56" },
  { value: "EU", label: "EU", example: "1.234,56" },
];

const CURRENCIES = [
  { value: "EUR", label: "Euro (EUR)" },
  { value: "USD", label: "US Dollar (USD)" },
  { value: "GBP", label: "British Pound (GBP)" },
  { value: "CHF", label: "Swiss Franc (CHF)" },
  { value: "JPY", label: "Japanese Yen (JPY)" },
  { value: "CAD", label: "Canadian Dollar (CAD)" },
  { value: "AUD", label: "Australian Dollar (AUD)" },
];

const COMMON_TIMEZONES = [
  { value: "UTC", label: "UTC" },
  { value: "Europe/London", label: "London (GMT/BST)" },
  { value: "Europe/Paris", label: "Paris (CET/CEST)" },
  { value: "Europe/Rome", label: "Rome (CET/CEST)" },
  { value: "Europe/Berlin", label: "Berlin (CET/CEST)" },
  { value: "America/New_York", label: "New York (EST/EDT)" },
  { value: "America/Chicago", label: "Chicago (CST/CDT)" },
  { value: "America/Los_Angeles", label: "Los Angeles (PST/PDT)" },
  { value: "Asia/Tokyo", label: "Tokyo (JST)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Australia/Sydney", label: "Sydney (AEST/AEDT)" },
];

// -----------------------------------------------------------------------------
// Form Schemas
// -----------------------------------------------------------------------------

const profileSchema = z.object({
  full_name: z.string().max(255).optional(),
});

const passwordSchema = z
  .object({
    current_password: z.string().min(1, "Current password is required"),
    new_password: z.string().min(8, "Password must be at least 8 characters"),
    confirm_password: z.string().min(1, "Please confirm your password"),
  })
  .refine((data) => data.new_password === data.confirm_password, {
    message: "Passwords don't match",
    path: ["confirm_password"],
  });

const deleteSchema = z.object({
  confirmation: z.string(),
  password: z.string().optional(),
});

type ProfileFormData = z.infer<typeof profileSchema>;
type PasswordFormData = z.infer<typeof passwordSchema>;
type DeleteFormData = z.infer<typeof deleteSchema>;

// -----------------------------------------------------------------------------
// Page Component
// -----------------------------------------------------------------------------

export default function SettingsPage() {
  const [showDeleteDialog, setShowDeleteDialog] = useState(false);

  // Queries
  const { data: settings, isLoading: settingsLoading } = useUserSettings();
  const { data: profile, isLoading: profileLoading } = useUserProfile();

  // Mutations
  const updateSettings = useUpdateUserSettings();
  const updateProfile = useUpdateUserProfile();
  const changePassword = useChangePassword();
  const deleteAccount = useDeleteAccount();

  // Forms
  const profileForm = useForm<ProfileFormData>({
    resolver: zodResolver(profileSchema),
    values: {
      full_name: profile?.full_name || "",
    },
  });

  const passwordForm = useForm<PasswordFormData>({
    resolver: zodResolver(passwordSchema),
    defaultValues: {
      current_password: "",
      new_password: "",
      confirm_password: "",
    },
  });

  const deleteForm = useForm<DeleteFormData>({
    resolver: zodResolver(deleteSchema),
    defaultValues: {
      confirmation: "",
      password: "",
    },
  });

  // Handlers
  const onProfileSubmit = async (data: ProfileFormData) => {
    try {
      await updateProfile.mutateAsync(data);
    } catch {
      // Error handled by mutation
    }
  };

  const onPasswordSubmit = async (data: PasswordFormData) => {
    try {
      await changePassword.mutateAsync({
        current_password: data.current_password,
        new_password: data.new_password,
      });
      passwordForm.reset();
    } catch {
      // Error handled by mutation
    }
  };

  const onDeleteSubmit = async (data: DeleteFormData) => {
    if (data.confirmation !== "DELETE") {
      deleteForm.setError("confirmation", {
        message: "Please type DELETE to confirm",
      });
      return;
    }
    try {
      await deleteAccount.mutateAsync({
        confirmation: "DELETE",
        password: data.password || undefined,
      });
    } catch {
      // Error handled by mutation
    }
  };

  const handleSettingChange = async (
    key: string,
    value: string | null
  ) => {
    try {
      await updateSettings.mutateAsync({ [key]: value });
    } catch {
      // Error handled by mutation
    }
  };

  const isLoading = settingsLoading || profileLoading;

  if (isLoading) {
    return (
      <div className="space-y-6 max-w-2xl">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage your account preferences
        </p>
      </div>

      {/* Profile Section */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <User className="h-5 w-5" />
            <CardTitle>Profile</CardTitle>
          </div>
          <CardDescription>Your personal information</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Avatar and Email */}
          <div className="flex items-center gap-4">
            <Avatar className="h-16 w-16">
              <AvatarImage src={profile?.picture_url || undefined} />
              <AvatarFallback>
                {profile?.full_name?.charAt(0) || profile?.email?.charAt(0) || "U"}
              </AvatarFallback>
            </Avatar>
            <div>
              <p className="font-medium">{profile?.email}</p>
              <p className="text-sm text-muted-foreground">
                {profile?.oauth_provider
                  ? `Signed in with ${profile.oauth_provider.charAt(0).toUpperCase() + profile.oauth_provider.slice(1)}`
                  : "Email account"}
              </p>
            </div>
          </div>

          <Separator />

          {/* Name Form */}
          <Form {...profileForm}>
            <form
              onSubmit={profileForm.handleSubmit(onProfileSubmit)}
              className="space-y-4"
            >
              <FormField
                control={profileForm.control}
                name="full_name"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Full Name</FormLabel>
                    <div className="flex gap-2">
                      <FormControl>
                        <Input
                          placeholder="Enter your name"
                          {...field}
                          value={field.value || ""}
                        />
                      </FormControl>
                      <Button
                        type="submit"
                        disabled={updateProfile.isPending}
                      >
                        {updateProfile.isPending && (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        )}
                        Save
                      </Button>
                    </div>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </form>
          </Form>
        </CardContent>
      </Card>

      {/* Display Preferences */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            <CardTitle>Display Preferences</CardTitle>
          </div>
          <CardDescription>Customize how data is displayed</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Theme */}
          <div className="space-y-2">
            <Label>Theme</Label>
            <Select
              value={settings?.theme || "system"}
              onValueChange={(value: string) => handleSettingChange("theme", value)}
            >
              <SelectTrigger className="w-full sm:w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {THEMES.map((theme) => (
                  <SelectItem key={theme.value} value={theme.value}>
                    {theme.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Separator />

          {/* Date Format */}
          <div className="space-y-2">
            <Label>Date Format</Label>
            <Select
              value={settings?.date_format || "YYYY-MM-DD"}
              onValueChange={(value: string) => handleSettingChange("date_format", value)}
            >
              <SelectTrigger className="w-full sm:w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {DATE_FORMATS.map((format) => (
                  <SelectItem key={format.value} value={format.value}>
                    {format.label} ({format.example})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <Separator />

          {/* Number Format */}
          <div className="space-y-2">
            <Label>Number Format</Label>
            <Select
              value={settings?.number_format || "US"}
              onValueChange={(value: string) => handleSettingChange("number_format", value)}
            >
              <SelectTrigger className="w-full sm:w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {NUMBER_FORMATS.map((format) => (
                  <SelectItem key={format.value} value={format.value}>
                    {format.label} ({format.example})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Portfolio Defaults */}
      <Card>
        <CardHeader>
          <CardTitle>Portfolio Defaults</CardTitle>
          <CardDescription>
            Default settings for new portfolios
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {/* Default Currency */}
          <div className="space-y-2">
            <Label>Default Currency</Label>
            <Select
              value={settings?.default_currency || "EUR"}
              onValueChange={(value: string) => handleSettingChange("default_currency", value)}
            >
              <SelectTrigger className="w-full sm:w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {CURRENCIES.map((currency) => (
                  <SelectItem key={currency.value} value={currency.value}>
                    {currency.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-sm text-muted-foreground">
              Currency used when creating new portfolios
            </p>
          </div>

          <Separator />

          {/* Default Benchmark */}
          <div className="space-y-2">
            <Label>Default Benchmark</Label>
            <Input
              value={settings?.default_benchmark || ""}
              onChange={(e) =>
                handleSettingChange(
                  "default_benchmark",
                  e.target.value || null
                )
              }
              placeholder="e.g., ^GSPC, ^STOXX50E"
              className="w-full sm:w-[240px]"
            />
            <p className="text-sm text-muted-foreground">
              Benchmark index for performance comparison (optional)
            </p>
          </div>

          <Separator />

          {/* Timezone */}
          <div className="space-y-2">
            <Label>Timezone</Label>
            <Select
              value={settings?.timezone || "UTC"}
              onValueChange={(value: string) => handleSettingChange("timezone", value)}
            >
              <SelectTrigger className="w-full sm:w-[240px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMMON_TIMEZONES.map((tz) => (
                  <SelectItem key={tz.value} value={tz.value}>
                    {tz.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardContent>
      </Card>

      {/* Security */}
      {profile?.has_password && (
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5" />
              <CardTitle>Security</CardTitle>
            </div>
            <CardDescription>Manage your password</CardDescription>
          </CardHeader>
          <CardContent>
            <Form {...passwordForm}>
              <form
                onSubmit={passwordForm.handleSubmit(onPasswordSubmit)}
                className="space-y-4"
              >
                <FormField
                  control={passwordForm.control}
                  name="current_password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Current Password</FormLabel>
                      <FormControl>
                        <Input type="password" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={passwordForm.control}
                  name="new_password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>New Password</FormLabel>
                      <FormControl>
                        <Input type="password" {...field} />
                      </FormControl>
                      <FormDescription>
                        At least 8 characters
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={passwordForm.control}
                  name="confirm_password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Confirm New Password</FormLabel>
                      <FormControl>
                        <Input type="password" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <Button type="submit" disabled={changePassword.isPending}>
                  {changePassword.isPending && (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  )}
                  Change Password
                </Button>
              </form>
            </Form>
          </CardContent>
        </Card>
      )}

      {/* Danger Zone */}
      <Card className="border-destructive/50">
        <CardHeader>
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-destructive" />
            <CardTitle className="text-destructive">Danger Zone</CardTitle>
          </div>
          <CardDescription>
            Irreversible actions that affect your account
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <p className="font-medium">Delete Account</p>
              <p className="text-sm text-muted-foreground">
                Permanently delete your account and all your data
              </p>
            </div>
            <AlertDialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
              <AlertDialogTrigger asChild>
                <Button variant="destructive">Delete Account</Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete your account?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This action cannot be undone. This will permanently delete
                    your account and all associated data including:
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <ul className="list-disc list-inside text-sm text-muted-foreground ml-2 space-y-1">
                  <li>All your portfolios</li>
                  <li>All transactions</li>
                  <li>All settings and preferences</li>
                </ul>
                <Form {...deleteForm}>
                  <form
                    onSubmit={deleteForm.handleSubmit(onDeleteSubmit)}
                    className="space-y-4 mt-4"
                  >
                    {profile?.has_password && (
                      <FormField
                        control={deleteForm.control}
                        name="password"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel>Password</FormLabel>
                            <FormControl>
                              <Input
                                type="password"
                                placeholder="Enter your password"
                                {...field}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    )}
                    <FormField
                      control={deleteForm.control}
                      name="confirmation"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>
                            Type <span className="font-mono font-bold">DELETE</span> to confirm
                          </FormLabel>
                          <FormControl>
                            <Input
                              placeholder="DELETE"
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <AlertDialogFooter>
                      <AlertDialogCancel
                        onClick={() => deleteForm.reset()}
                      >
                        Cancel
                      </AlertDialogCancel>
                      <Button
                        type="submit"
                        variant="destructive"
                        disabled={deleteAccount.isPending}
                      >
                        {deleteAccount.isPending ? (
                          <>
                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                            Deleting...
                          </>
                        ) : (
                          "Delete Account"
                        )}
                      </Button>
                    </AlertDialogFooter>
                  </form>
                </Form>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
