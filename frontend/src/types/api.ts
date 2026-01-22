// =============================================================================
// API Types for Investment Portfolio Analyzer
// =============================================================================
// These types match the backend Pydantic schemas
// Financial values use string to preserve decimal precision
// =============================================================================

// -----------------------------------------------------------------------------
// Enums
// -----------------------------------------------------------------------------

export type TransactionType =
  | "BUY"
  | "SELL"
  | "DEPOSIT"
  | "WITHDRAWAL"
  | "DIVIDEND"
  | "FEE"
  | "TAX";

export type AssetClass =
  | "STOCK"
  | "ETF"
  | "BOND"
  | "OPTION"
  | "CRYPTO"
  | "CASH"
  | "INDEX"
  | "FUTURE"
  | "OTHER";

export type SyncStatus =
  | "NEVER"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "PARTIAL"
  | "FAILED"
  | "PENDING";

// -----------------------------------------------------------------------------
// Pagination
// -----------------------------------------------------------------------------

export interface PaginationMeta {
  total: number;
  skip: number;
  limit: number;
  page: number;
  pages: number;
  has_next: boolean;
  has_previous: boolean;
}

// -----------------------------------------------------------------------------
// Auth Types
// -----------------------------------------------------------------------------

export interface UserRegisterRequest {
  email: string;
  password: string;
  full_name?: string | null;
}

export interface UserLoginRequest {
  email: string;
  password: string;
}

export interface TokenRefreshRequest {
  refresh_token: string;
}

export interface VerifyEmailRequest {
  token: string;
}

export interface ResendVerificationRequest {
  email: string;
}

export interface ForgotPasswordRequest {
  email: string;
}

export interface ResetPasswordRequest {
  token: string;
  new_password: string;
}

export interface LogoutRequest {
  refresh_token: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  picture_url: string | null;
  is_email_verified: boolean;
  oauth_provider: string | null;
  created_at: string;
}

export interface MessageResponse {
  message: string;
}

export interface GoogleAuthUrlResponse {
  authorization_url: string;
  state: string;
}

// -----------------------------------------------------------------------------
// User Settings Types
// -----------------------------------------------------------------------------

export type Theme = "light" | "dark" | "system";
export type DateFormat = "YYYY-MM-DD" | "MM/DD/YYYY" | "DD/MM/YYYY";
export type NumberFormat = "US" | "EU";

export interface UserSettings {
  theme: Theme;
  date_format: DateFormat;
  number_format: NumberFormat;
  default_currency: string;
  default_benchmark: string | null;
  timezone: string;
}

export interface UserSettingsUpdate {
  theme?: Theme | null;
  date_format?: DateFormat | null;
  number_format?: NumberFormat | null;
  default_currency?: string | null;
  default_benchmark?: string | null;
  timezone?: string | null;
}

// -----------------------------------------------------------------------------
// User Profile Types
// -----------------------------------------------------------------------------

export interface UserProfile {
  id: number;
  email: string;
  full_name: string | null;
  picture_url: string | null;
  has_password: boolean;
  oauth_provider: string | null;
  created_at: string;
}

export interface UserProfileUpdate {
  full_name?: string | null;
}

export interface PasswordChangeRequest {
  current_password: string;
  new_password: string;
}

export interface AccountDeleteRequest {
  password?: string | null;
  confirmation: string;
}

// -----------------------------------------------------------------------------
// Asset Types
// -----------------------------------------------------------------------------

export interface AssetCreate {
  ticker: string;
  exchange: string;
  isin?: string | null;
  name?: string | null;
  asset_class?: AssetClass;
  currency?: string;
  sector?: string | null;
  region?: string | null;
  is_active?: boolean;
}

export interface AssetUpdate {
  ticker?: string | null;
  exchange?: string | null;
  isin?: string | null;
  name?: string | null;
  asset_class?: AssetClass | null;
  currency?: string | null;
  sector?: string | null;
  region?: string | null;
  is_active?: boolean | null;
  proxy_asset_id?: number | null;
  proxy_notes?: string | null;
}

export interface Asset {
  id: number;
  ticker: string;
  exchange: string;
  isin: string | null;
  name: string | null;
  asset_class: AssetClass;
  currency: string;
  sector: string | null;
  region: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  proxy_asset_id: number | null;
  proxy_notes: string | null;
}

export interface AssetListResponse {
  items: Asset[];
  pagination: PaginationMeta;
}

// -----------------------------------------------------------------------------
// Portfolio Types
// -----------------------------------------------------------------------------

export interface PortfolioCreate {
  name: string;
  currency?: string;
}

export interface PortfolioUpdate {
  name?: string | null;
  currency?: string | null;
}

export interface Portfolio {
  id: number;
  user_id: number;
  name: string;
  currency: string;
  created_at: string;
  updated_at: string;
}

export interface PortfolioListResponse {
  items: Portfolio[];
  pagination: PaginationMeta;
}

// -----------------------------------------------------------------------------
// Transaction Types
// -----------------------------------------------------------------------------

export interface TransactionCreate {
  portfolio_id: number;
  ticker: string;
  exchange: string;
  transaction_type: TransactionType;
  date: string;
  quantity: string;
  price_per_share: string;
  currency?: string;
  fee?: string;
  fee_currency?: string | null;
  exchange_rate?: string | null;
}

export interface TransactionUpdate {
  date?: string | null;
  quantity?: string | null;
  price_per_share?: string | null;
  currency?: string | null;
  fee?: string | null;
  fee_currency?: string | null;
  exchange_rate?: string | null;
}

export interface Transaction {
  id: number;
  portfolio_id: number;
  asset_id: number;
  transaction_type: TransactionType;
  date: string;
  quantity: string;
  price_per_share: string;
  currency: string;
  fee: string;
  fee_currency: string | null;
  exchange_rate: string | null;
  created_at: string;
  asset: Asset;
}

export interface TransactionWithTotals extends Transaction {
  total_value: string;
  total_cost: string;
}

export interface TransactionListResponse {
  items: Transaction[];
  pagination: PaginationMeta;
}

// -----------------------------------------------------------------------------
// Valuation Types
// -----------------------------------------------------------------------------

export interface CostBasisDetail {
  local_currency: string;
  local_amount: string;
  portfolio_currency: string;
  portfolio_amount: string;
  avg_cost_per_share: string;
}

export interface CurrentValueDetail {
  price_per_share: string | null;
  price_date: string | null;
  local_currency: string;
  local_amount: string | null;
  portfolio_currency: string;
  portfolio_amount: string | null;
  fx_rate_used: string | null;
}

export interface PnLDetail {
  unrealized_amount: string | null;
  unrealized_percentage: string | null;
  realized_amount: string;
  realized_percentage: string | null;
  total_amount: string | null;
  total_percentage: string | null;
}

export interface HoldingValuation {
  asset_id: number;
  ticker: string;
  exchange: string;
  asset_name: string | null;
  asset_currency: string;
  quantity: string;
  cost_basis: CostBasisDetail;
  current_value: CurrentValueDetail;
  pnl: PnLDetail;
  warnings: string[];
  has_complete_data: boolean;
  price_is_synthetic: boolean;
  price_source: string;
  proxy_ticker: string | null;
  proxy_exchange: string | null;
}

export interface CashBalanceDetail {
  currency: string;
  amount: string;
  amount_portfolio: string | null;
  fx_rate_used: string | null;
}

export interface PortfolioValuationSummary {
  total_cost_basis: string;
  total_value: string | null;
  total_cash: string | null;
  total_equity: string | null;
  total_unrealized_pnl: string | null;
  total_realized_pnl: string;
  total_pnl: string | null;
  total_pnl_percentage: string | null;
}

export interface PortfolioValuation {
  portfolio_id: number;
  portfolio_name: string;
  portfolio_currency: string;
  valuation_date: string;
  summary: PortfolioValuationSummary;
  holdings: HoldingValuation[];
  tracks_cash: boolean;
  cash_balances: CashBalanceDetail[];
  has_complete_data: boolean;
  warnings: string[];
  has_synthetic_data: boolean;
  synthetic_holdings_count: number;
}

export interface ValuationHistoryPoint {
  date: string;
  value: string | null;
  cash: string | null;
  equity: string | null;
  cost_basis: string;
  unrealized_pnl: string | null;
  realized_pnl: string;
  total_pnl: string | null;
  pnl_percentage: string | null;
  has_complete_data: boolean;
  has_synthetic_data: boolean;
  synthetic_holdings: string[];
}

export interface PortfolioHistory {
  portfolio_id: number;
  portfolio_currency: string;
  from_date: string;
  to_date: string;
  interval: string;
  tracks_cash: boolean;
  data: ValuationHistoryPoint[];
  total_points: number;
  warnings: string[];
  has_synthetic_data: boolean;
  synthetic_holdings: Record<string, string | null>;
  synthetic_date_range: [string, string] | null;
  synthetic_data_percentage: string;
}

export interface ValuationRequest {
  date?: string | null;
}

export interface ValuationHistoryRequest {
  from_date: string;
  to_date: string;
  interval?: "daily" | "weekly" | "monthly";
}

// -----------------------------------------------------------------------------
// Analytics Types
// -----------------------------------------------------------------------------

export interface PeriodInfo {
  from_date: string;
  to_date: string;
  trading_days: number;
  calendar_days: number;
}

export interface PerformanceMetrics {
  simple_return: string | null;
  simple_return_annualized: string | null;
  total_realized_pnl: string | null;
  twr: string | null;
  twr_annualized: string | null;
  cagr: string | null;
  xirr: string | null;
  total_gain: string | null;
  start_value: string | null;
  end_value: string | null;
  cost_basis: string | null;
  total_deposits: string;
  total_withdrawals: string;
  net_invested: string | null;
  has_sufficient_data: boolean;
  warnings: string[];
}

export interface PerformanceResponse {
  portfolio_id: number;
  portfolio_currency: string;
  period: PeriodInfo;
  performance: PerformanceMetrics;
}

export interface DrawdownPeriod {
  start_date: string;
  trough_date: string;
  end_date: string | null;
  depth: string;
  duration_days: number;
  recovery_days: number | null;
}

export interface InvestmentPeriod {
  period_index: number;
  start_date: string;
  end_date: string | null;
  is_active: boolean;
  contribution_date: string | null;
  contribution_value: string | null;
  start_value: string | null;
  end_value: string | null;
  trading_days: number;
}

export interface MeasurementPeriod {
  period_type: "active" | "historical" | "full";
  start_date: string;
  end_date: string;
  trading_days: number;
  description: string | null;
}

export interface RiskMetrics {
  volatility_daily: string | null;
  volatility_annualized: string | null;
  downside_deviation: string | null;
  sharpe_ratio: string | null;
  sortino_ratio: string | null;
  calmar_ratio: string | null;
  max_drawdown: string | null;
  max_drawdown_start: string | null;
  max_drawdown_end: string | null;
  current_drawdown: string | null;
  var_95: string | null;
  cvar_95: string | null;
  positive_days: number;
  negative_days: number;
  win_rate: string | null;
  best_day: string | null;
  best_day_date: string | null;
  worst_day: string | null;
  worst_day_date: string | null;
  drawdown_periods: DrawdownPeriod[];
  measurement_period: MeasurementPeriod | null;
  investment_periods: InvestmentPeriod[];
  total_periods: number;
  scope: string;
  has_sufficient_data: boolean;
  warnings: string[];
}

export interface RiskResponse {
  portfolio_id: number;
  portfolio_currency: string;
  period: PeriodInfo;
  risk: RiskMetrics;
}

export interface BenchmarkMetrics {
  benchmark_symbol: string;
  benchmark_name: string | null;
  portfolio_return: string | null;
  benchmark_return: string | null;
  excess_return: string | null;
  beta: string | null;
  alpha: string | null;
  correlation: string | null;
  r_squared: string | null;
  tracking_error: string | null;
  information_ratio: string | null;
  up_capture: string | null;
  down_capture: string | null;
  has_sufficient_data: boolean;
  warnings: string[];
}

export interface BenchmarkResponse {
  portfolio_id: number;
  portfolio_currency: string;
  period: PeriodInfo;
  benchmark: BenchmarkMetrics;
}

export interface SyntheticAssetDetail {
  ticker: string;
  proxy_ticker: string | null;
  first_synthetic_date: string;
  last_synthetic_date: string;
  synthetic_days: number;
  total_days_held: number;
  percentage: string;
}

export interface AnalyticsResponse {
  portfolio_id: number;
  portfolio_currency: string;
  period: PeriodInfo;
  performance: PerformanceMetrics;
  risk: RiskMetrics;
  benchmark: BenchmarkMetrics | null;
  has_complete_data: boolean;
  warnings: string[];
  has_synthetic_data: boolean;
  synthetic_data_percentage: string | null;
  synthetic_holdings: Record<string, string | null>;
  synthetic_date_range: [string, string] | null;
  synthetic_details: Record<string, SyntheticAssetDetail>;
  reliability_notes: string[];
}

export interface AnalyticsQueryParams {
  from_date: string;
  to_date: string;
  benchmark_symbol?: string | null;
  risk_free_rate?: string;
}

// -----------------------------------------------------------------------------
// Sync Types
// -----------------------------------------------------------------------------

export interface SyncStatusResponse {
  portfolio_id: number;
  status: SyncStatus;
  started_at: string | null;
  completed_at: string | null;
  assets_synced: number;
  assets_failed: number;
  message: string | null;
}

export interface SyncTriggerResponse {
  message: string;
  status: SyncStatus;
}

// -----------------------------------------------------------------------------
// Upload Types
// -----------------------------------------------------------------------------

export type UploadDateFormat = "ISO" | "US" | "EU" | "AUTO";

export interface UploadResult {
  success: boolean;
  filename: string;
  total_rows: number;
  created_count: number;
  error_count: number;
  errors: Array<{
    row_number: number;
    stage: string;
    error_type: string;
    message: string;
    field: string | null;
  }>;
  warnings: Array<{
    row_number: number;
    stage: string;
    error_type: string;
    message: string;
    field: string | null;
  }>;
  created_transaction_ids: number[];
}

// For backwards compatibility
export interface UploadResultLegacy {
  success_count: number;
  error_count: number;
  errors: Array<{
    row: number;
    field: string;
    message: string;
  }>;
}

export interface DateSample {
  raw_value: string;
  row_number: number;
  us_interpretation: string | null;
  eu_interpretation: string | null;
  iso_interpretation: string | null;
  is_disambiguator: boolean;
}

export interface DateDetectionResult {
  status: "unambiguous" | "ambiguous" | "error";
  detected_format: "ISO" | "US" | "EU" | null;
  samples: DateSample[];
  reason: string;
}

export interface AmbiguousDateFormatError {
  error: "ambiguous_date_format";
  message: string;
  detection: DateDetectionResult;
}

// -----------------------------------------------------------------------------
// Error Types
// -----------------------------------------------------------------------------

export interface ErrorDetail {
  error: string;
  message: string;
  details: Record<string, unknown> | null;
}

export interface ValidationErrorDetail {
  error: string;
  message: string;
  details: Array<{
    field: string;
    message: string;
    type: string;
  }>;
}
