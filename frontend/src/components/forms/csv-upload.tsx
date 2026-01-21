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
import { useUploadTransactions } from "@/hooks/use-transactions";
import type { UploadResult } from "@/types/api";

interface CsvUploadProps {
  portfolioId: number;
  onSuccess?: () => void;
}

export function CsvUpload({ portfolioId, onSuccess }: CsvUploadProps) {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);
  const [showResult, setShowResult] = useState(false);
  const uploadMutation = useUploadTransactions();

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      setResult(null);
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

  const handleUpload = async () => {
    if (!file) return;

    try {
      const uploadResult = await uploadMutation.mutateAsync({
        portfolioId,
        file,
      });
      setResult(uploadResult);
      setShowResult(true);
      if (uploadResult.error_count === 0) {
        setFile(null);
        onSuccess?.();
      }
    } catch {
      // Error handled by mutation
    }
  };

  const handleClear = () => {
    setFile(null);
    setResult(null);
  };

  const closeResultDialog = () => {
    setShowResult(false);
    if (result && result.error_count === 0) {
      setFile(null);
      setResult(null);
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
            onClick={handleUpload}
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
              <strong>date:</strong> YYYY-MM-DD format
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
              {result.success_count > 0 && (
                <Alert>
                  <CheckCircle2 className="h-4 w-4 text-green-500" />
                  <AlertTitle>Success</AlertTitle>
                  <AlertDescription>
                    {result.success_count} transaction
                    {result.success_count !== 1 ? "s" : ""} imported successfully.
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
                          <td className="p-2">{error.row}</td>
                          <td className="p-2">{error.field}</td>
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
