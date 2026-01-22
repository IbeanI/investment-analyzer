"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import {
  Upload,
  FileSpreadsheet,
  X,
  CheckCircle2,
  AlertCircle,
  Loader2,
  HelpCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useUploadTransactions, AmbiguousDateFormatException } from "@/hooks/use-transactions";
import type { UploadResult, DateDetectionResult, UploadDateFormat } from "@/types/api";

interface CsvUploadProps {
  portfolioId: number;
  onSuccess?: () => void;
}

export function CsvUpload({ portfolioId, onSuccess }: CsvUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [showResult, setShowResult] = useState(false);
  const [dateDetection, setDateDetection] = useState<DateDetectionResult | null>(null);
  const [showDateFormatDialog, setShowDateFormatDialog] = useState(false);
  const uploadMutation = useUploadTransactions();

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setResult(null);
      setDateDetection(null);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "text/csv": [".csv"],
      "application/vnd.ms-excel": [".csv"],
    },
    maxFiles: 1,
    maxSize: 5 * 1024 * 1024, // 5MB
  });

  const handleUpload = async (dateFormat?: UploadDateFormat) => {
    if (!file) return;

    try {
      const uploadResult = await uploadMutation.mutateAsync({
        portfolioId,
        file,
        dateFormat,
      });
      setResult(uploadResult);
      setShowResult(true);
      setShowDateFormatDialog(false);
      setDateDetection(null);
      if (uploadResult.error_count === 0) {
        setFile(null);
        onSuccess?.();
      }
    } catch (error) {
      if (error instanceof AmbiguousDateFormatException) {
        setDateDetection(error.detection);
        setShowDateFormatDialog(true);
      }
      // Other errors handled by mutation
    }
  };

  const handleFormatSelect = (format: "US" | "EU") => {
    handleUpload(format);
  };

  const handleClear = () => {
    setFile(null);
    setResult(null);
    setDateDetection(null);
  };

  const closeResultDialog = () => {
    setShowResult(false);
    if (result && result.error_count === 0) {
      setFile(null);
      setResult(null);
    }
  };

  const closeDateFormatDialog = () => {
    setShowDateFormatDialog(false);
    setDateDetection(null);
  };

  // Format a date string for display (e.g., "2021-01-22" -> "Jan 22, 2021")
  const formatDateForDisplay = (isoDate: string | null): string => {
    if (!isoDate) return "-";
    try {
      const date = new Date(isoDate + "T00:00:00");
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return isoDate;
    }
  };

  return (
    <div className="space-y-4">
      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={cn(
          "border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors",
          isDragActive
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-primary/50",
          file && "border-primary bg-primary/5"
        )}
      >
        <input {...getInputProps()} />
        <div className="flex flex-col items-center gap-3">
          {file ? (
            <>
              <FileSpreadsheet className="h-12 w-12 text-primary" />
              <div>
                <p className="font-medium">{file.name}</p>
                <p className="text-sm text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB
                </p>
              </div>
            </>
          ) : (
            <>
              <Upload className="h-12 w-12 text-muted-foreground" />
              <div>
                <p className="font-medium">
                  {isDragActive
                    ? "Drop the file here"
                    : "Drag & drop your CSV file"}
                </p>
                <p className="text-sm text-muted-foreground">
                  or click to browse (max 5MB)
                </p>
              </div>
            </>
          )}
        </div>
      </div>

      {/* File actions */}
      {file && (
        <div className="flex gap-2">
          <Button
            onClick={() => handleUpload()}
            disabled={uploadMutation.isPending}
            className="flex-1"
          >
            {uploadMutation.isPending ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Uploading...
              </>
            ) : (
              <>
                <Upload className="mr-2 h-4 w-4" />
                Upload
              </>
            )}
          </Button>
          <Button variant="outline" onClick={handleClear}>
            <X className="h-4 w-4" />
          </Button>
        </div>
      )}

      {/* CSV format info */}
      <Card className="bg-muted/50">
        <CardContent className="pt-4">
          <h4 className="text-sm font-medium mb-2">Expected CSV Format</h4>
          <p className="text-xs text-muted-foreground mb-2">
            Your CSV file should have the following columns:
          </p>
          <code className="text-xs block bg-background p-2 rounded">
            date,ticker,exchange,type,quantity,price,currency,fee
          </code>
          <ul className="text-xs text-muted-foreground mt-2 space-y-1">
            <li>
              <strong>date:</strong> Auto-detected (YYYY-MM-DD, M/D/YYYY, or D/M/YYYY)
            </li>
            <li>
              <strong>type:</strong> BUY or SELL
            </li>
            <li>
              <strong>exchange:</strong> optional (e.g., NASDAQ, NYSE)
            </li>
            <li>
              <strong>fee:</strong> optional
            </li>
          </ul>
        </CardContent>
      </Card>

      {/* Date format confirmation dialog */}
      <Dialog open={showDateFormatDialog} onOpenChange={setShowDateFormatDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <HelpCircle className="h-5 w-5 text-amber-500" />
              Confirm Date Format
            </DialogTitle>
            <DialogDescription>
              We couldn&apos;t automatically determine your date format. Please select
              the correct interpretation.
            </DialogDescription>
          </DialogHeader>

          {dateDetection && (
            <div className="space-y-4">
              {/* Sample dates table */}
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50">
                    <tr>
                      <th className="p-2 text-left w-16">Row</th>
                      <th className="p-2 text-left">Raw Value</th>
                      <th className="p-2 text-left">US (M/D/Y)</th>
                      <th className="p-2 text-left">EU (D/M/Y)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dateDetection.samples.map((sample) => (
                      <tr key={sample.row_number} className="border-t">
                        <td className="p-2 font-mono text-muted-foreground">
                          {sample.row_number}
                        </td>
                        <td className="p-2 font-mono">
                          {sample.raw_value}
                        </td>
                        <td className="p-2">
                          {formatDateForDisplay(sample.us_interpretation)}
                        </td>
                        <td className="p-2">
                          {formatDateForDisplay(sample.eu_interpretation)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Format selection buttons */}
              <div className="flex gap-3">
                <Button
                  onClick={() => handleFormatSelect("US")}
                  disabled={uploadMutation.isPending}
                  className="flex-1"
                  variant="outline"
                >
                  {uploadMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : null}
                  Use US Format (M/D/YYYY)
                </Button>
                <Button
                  onClick={() => handleFormatSelect("EU")}
                  disabled={uploadMutation.isPending}
                  className="flex-1"
                  variant="outline"
                >
                  {uploadMutation.isPending ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : null}
                  Use EU Format (D/M/YYYY)
                </Button>
              </div>

              <Button
                variant="ghost"
                onClick={closeDateFormatDialog}
                className="w-full"
              >
                Cancel
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Result dialog */}
      <Dialog open={showResult} onOpenChange={setShowResult}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Upload Complete</DialogTitle>
            <DialogDescription>
              Your CSV file has been processed.
            </DialogDescription>
          </DialogHeader>

          {result && (
            <div className="space-y-4">
              {/* Success summary */}
              {result.created_count > 0 && (
                <Alert>
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                  <AlertTitle>Success</AlertTitle>
                  <AlertDescription>
                    {result.created_count} transaction
                    {result.created_count !== 1 ? "s" : ""} imported successfully.
                  </AlertDescription>
                </Alert>
              )}

              {/* Error summary */}
              {result.error_count > 0 && (
                <Alert variant="destructive">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Errors</AlertTitle>
                  <AlertDescription>
                    {result.error_count} row{result.error_count !== 1 ? "s" : ""}{" "}
                    failed to import.
                  </AlertDescription>
                </Alert>
              )}

              {/* Error details */}
              {result.errors && result.errors.length > 0 && (
                <div className="max-h-48 overflow-y-auto border rounded-lg">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/50 sticky top-0">
                      <tr>
                        <th className="p-2 text-left">Row</th>
                        <th className="p-2 text-left">Field</th>
                        <th className="p-2 text-left">Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.errors.map((error, i) => (
                        <tr key={i} className="border-t">
                          <td className="p-2">{error.row_number}</td>
                          <td className="p-2">{error.field || "-"}</td>
                          <td className="p-2 text-muted-foreground">
                            {error.message}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <Button onClick={closeResultDialog} className="w-full">
                {result.error_count > 0 ? "Close" : "Done"}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
