# Investment Analyzer - Code Review Report

**Date:** January 22, 2026
**Reviewed By:** Claude Code
**Scope:** Full-stack application (Backend + Frontend + Database + Security + Testing)

---

## Executive Summary

The Investment Analyzer is a well-architected full-stack application with solid foundational patterns. The backend demonstrates excellent financial calculation precision and query optimization. However, there are **6 critical issues** and **7 high-priority issues** that should be addressed before production deployment, primarily around security (token storage, secrets management) and data integrity (transaction validation, cascade deletes).

**Overall Assessment:** Development-ready, requires remediation for production.

---

## Critical Issues (Fix Immediately)

### 1. [SECURITY] JWT Tokens Stored in localStorage (XSS Vulnerable)
- **Location:** `frontend/src/lib/api/client.ts:8-35`
- **Risk:** Any XSS vulnerability grants attackers complete session access
- **Fix:** Move tokens to httpOnly, Secure, SameSite=Strict cookies
- **Effort:** Medium

### 2. [SECURITY] Secrets Committed to Git
- **Location:** `.env` file in repository
- **Risk:** Database credentials, JWT secret exposed to anyone with repo access
- **Fix:**
  - Remove `.env` from git history using `git filter-repo`
  - Rotate all secrets immediately
  - Create `.env.example` template instead
- **Effort:** Low

### 3. [BACKEND] SELL Transactions Accepted Without Validating Holdings
- **Location:** `backend/app/routers/transactions.py:143-210`
- **Risk:** Users can create invalid negative positions accidentally
- **Fix:** Add validation before SELL:
  ```python
  def validate_sell_quantity(db, portfolio_id, asset_id, sell_qty):
      holdings = get_current_holdings(db, portfolio_id, asset_id)
      if holdings.quantity < sell_qty:
          raise ValueError(f"Cannot sell {sell_qty}; only {holdings.quantity} held")
  ```
- **Effort:** Medium

### 4. [BACKEND] Exchange Rate Convention Complexity
- **Location:** `backend/app/services/valuation/calculators.py:130-169`
- **Risk:** Transaction convention vs FX service convention are inverses; easy to introduce subtle calculation errors
- **Fix:** Create explicit conversion functions:
  ```python
  def transaction_rate_to_fx_rate(txn_rate: Decimal) -> Decimal:
      """Convert broker convention to FX service convention."""
      return Decimal("1") / txn_rate
  ```
- **Effort:** Low

### 5. [DATABASE] Missing ON DELETE CASCADE
- **Location:** `backend/app/models.py:215,303,304`
- **Risk:** Deleting users/portfolios leaves orphaned data, breaks referential integrity
- **Affected FKs:**
  - `Portfolio.user_id` → should cascade from User
  - `Transaction.portfolio_id` → should cascade from Portfolio
  - `Transaction.asset_id` → should handle asset deletion
- **Fix:** Add `ondelete="CASCADE"` to ForeignKey definitions and create migration
- **Effort:** Medium

### 6. [FRONTEND] Query Key Cache Invalidation Bugs
- **Location:** `frontend/src/hooks/use-portfolios.ts:68-73,95-107`
- **Risk:** Changing date/benchmark parameters doesn't update cached results
- **Fix:**
  ```typescript
  // Before (broken):
  queryKey: portfolioKeys.valuation(id),

  // After (correct):
  queryKey: [...portfolioKeys.valuation(id), date?.toISOString()],
  ```
- **Effort:** Low

---

## High Priority Issues (Fix Before Production)

### 7. [SECURITY] CORS Misconfiguration
- **Location:** `backend/app/config.py:201-207`
- **Issue:** `allow_methods=["*"]` and `allow_headers=["*"]` are overly permissive
- **Fix:** Explicitly list allowed methods and headers:
  ```python
  cors_allow_methods: list[str] = Field(
      default=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
  )
  cors_allow_headers: list[str] = Field(
      default=["Content-Type", "Authorization"]
  )
  ```

### 8. [SECURITY] X-Forwarded-For Without Proxy Validation
- **Location:** `backend/app/middleware/rate_limit.py:70-74`
- **Issue:** Trusts X-Forwarded-For header from any source; allows rate limit bypass
- **Fix:** Only trust header when request comes from known proxy IPs

### 9. [BACKEND] Batch Operation Error Messages
- **Location:** `backend/app/routers/transactions.py:579-591`
- **Issue:** All-or-nothing semantics with generic error messages
- **Fix:** Return detailed per-transaction status:
  ```json
  {
    "status": "partial_failure",
    "successful": [1, 2],
    "failed": [{"index": 3, "ticker": "INVALID", "reason": "not_found"}]
  }
  ```

### 10. [BACKEND] Silent Data Integrity Failures
- **Location:** `backend/app/services/valuation/calculators.py:100-108`
- **Issue:** Invalid positions (sales without buys) logged but skipped silently
- **Fix:** Include warnings in valuation response so users see data issues

### 11. [FRONTEND] Skip Link Accessibility (WCAG 2.4.1)
- **Location:** `frontend/src/app/(dashboard)/layout.tsx:54-60`
- **Issue:** Skip link has undefined `skip-link` CSS class, never visible
- **Fix:** Add proper focus-visible styling for keyboard users

### 12. [FRONTEND] Chart Legend Keyboard Accessibility (WCAG 2.1.1)
- **Location:** `frontend/src/components/charts/allocation-chart.tsx:231-246`
- **Issue:** Legend items are interactive (hover) but lack keyboard support
- **Fix:** Add `role="button"`, `tabIndex={0}`, and keyboard event handlers

### 13. [TESTING] No Frontend Tests
- **Location:** `frontend/`
- **Issue:** Zero test coverage for React components, hooks, or E2E flows
- **Fix:** Set up Vitest + React Testing Library, prioritize auth and transaction forms

---

## Medium Priority Issues

### Backend

| Issue | Location | Description |
|-------|----------|-------------|
| DRY violations | `transactions.py`, `dependencies.py` | Ownership checks duplicated in multiple places |
| Future date validation | `schemas/transactions.py` | Transaction dates can be in the future |
| SQL error leaking | `transactions.py:620-646` | IntegrityError details exposed to clients |
| Benchmark validation | `analytics/service.py` | Missing check that benchmark data exists |
| Currency column size | `models.py:263,313` | `Asset.currency` and `Transaction.currency` unbounded |
| Fee currency default | `models.py:315` | `fee_currency` has no default value |

### Frontend

| Issue | Location | Description |
|-------|----------|-------------|
| Missing useCallback | `use-portfolios.ts`, `use-transactions.ts` | Mutation handlers recreated every render |
| Silent auth errors | `auth-provider.tsx:81-84` | Auth failures caught but not shown to user |
| Color-only charts | `value-chart.tsx:116-123` | Green/red only - colorblind inaccessible |
| Table ARIA | `holdings-table.tsx:173-204` | Missing caption, aria-sort, scope attributes |
| Error toast pattern | Multiple hooks | Same error handling repeated 15+ times |
| Type safety gaps | `allocation-chart.tsx:208-213` | Unsafe `as` casts for Recharts props |

### Security

| Issue | Location | Description |
|-------|----------|-------------|
| Debug mode | `.env` | `DEBUG=true` must be false in production |
| PII storage | `models.py:195-196` | Device/IP stored as plaintext (GDPR concern) |
| In-memory rate limiting | `rate_limit.py` | Doesn't work across multiple instances |
| Database credentials | `config.py:24` | Embedded in connection string |

### Database

| Issue | Location | Description |
|-------|----------|-------------|
| Missing index | `RefreshToken` | Need `(user_id, revoked_at)` for active token lookups |
| No CHECK constraints | Price columns | Nothing prevents negative prices |
| Incomplete soft-delete | `Asset.is_active` | Flag exists but not consistently used |
| Missing covering index | `ExchangeRate` | Could optimize upsert operations |

---

## Positive Findings

### Backend Strengths
- **Batch Query Optimization:** ValuationService, HistoryCalculator, and SyncService all avoid N+1 queries through strategic batch fetches
- **Financial Precision:** `Decimal(18, 8)` correctly sized for crypto and forex
- **Token Security:** Enterprise-grade refresh token rotation with replay attack detection
- **Validation:** Comprehensive Pydantic v2 validators for all inputs
- **Error Hierarchy:** Well-designed domain exceptions with no HTTP coupling
- **Documentation:** Extensive code comments explaining financial conventions

### Frontend Strengths
- **React Query:** Proper server state management with query keys
- **Form Handling:** React Hook Form + Zod validation matching backend
- **UI Components:** Clean shadcn/ui integration with dark mode
- **Loading States:** Consistent loading and empty state handling
- **Responsive:** Mobile-first design with Tailwind

### Testing Strengths
- **Coverage:** 731 backend tests across 32 files
- **Financial Tests:** Excellent edge case coverage for TWR, XIRR, CAGR, Sharpe, etc.
- **Fixtures:** Well-structured pytest fixtures with isolated databases
- **Mocking:** Flexible MockMarketDataProvider for testing failures

---

## Test Coverage Summary

| Area | Tests | Coverage | Assessment |
|------|-------|----------|------------|
| Backend Unit | 330+ | High | Excellent financial calculation tests |
| Backend Integration | 290+ | Good | API endpoints well covered |
| Backend E2E | ~110 | Moderate | Basic workflows covered |
| Frontend | 0 | None | Critical gap |
| Performance | 0 | None | No scalability tests |

### Missing Test Areas
- Frontend component tests
- Concurrent operation tests (race conditions)
- Large dataset performance tests
- Cash tracking (DEPOSIT/WITHDRAWAL) tests
- File upload edge cases (large files, encoding)

---

## Remediation Plan

### Phase 1: Security Hardening (Before Production)
1. Move JWT tokens to httpOnly cookies
2. Remove `.env` from git history, rotate all secrets
3. Fix CORS configuration (explicit methods/headers)
4. Add trusted proxy validation for X-Forwarded-For
5. Ensure `DEBUG=false` in production

### Phase 2: Data Integrity
6. Add SELL quantity validation
7. Add `ON DELETE CASCADE` to FKs (create migration)
8. Fix query key cache invalidation bugs
9. Add CHECK constraints for positive financial values
10. Fix `fee_currency` default

### Phase 3: User Experience
11. Fix accessibility issues (skip link, keyboard nav, ARIA)
12. Improve error handling (detailed batch errors, visible auth errors)
13. Add `useCallback` memoization to hooks
14. Fix color-only chart information

### Phase 4: Testing Infrastructure
15. Set up Vitest + React Testing Library for frontend
16. Add concurrent operation tests
17. Add E2E workflow tests with Playwright
18. Add performance benchmarks

### Phase 5: Code Quality
19. Consolidate ownership check logic (DRY)
20. Extract reusable error toast handler
21. Add explicit lazy loading strategy to relationships
22. Complete or remove Asset soft-delete

---

## Severity Matrix

```
                    CRITICAL   HIGH   MEDIUM   LOW
Security               2        2       3       2
Backend Logic          2        2       4       3
Frontend               1        2       4       5
Database               1        0       4       2
Testing                0        1       3       2
─────────────────────────────────────────────────
TOTAL                  6        7      18      14
```

---

## Files Reference

### Critical Files to Review
- `frontend/src/lib/api/client.ts` - Token storage
- `backend/app/routers/transactions.py` - SELL validation, batch errors
- `backend/app/services/valuation/calculators.py` - FX conventions
- `backend/app/models.py` - FK cascades, constraints
- `frontend/src/hooks/use-portfolios.ts` - Query keys

### Configuration Files
- `.env` - Secrets (should not exist in repo)
- `backend/app/config.py` - CORS, JWT, debug settings
- `backend/app/middleware/rate_limit.py` - Rate limiting

### Test Files
- `backend/tests/` - 731 tests, well-organized
- `frontend/` - No tests (needs setup)

---

## Next Steps

1. **Immediate:** Address Critical issues #1-6
2. **This Sprint:** Address High priority issues #7-13
3. **Next Sprint:** Address Medium priority issues
4. **Ongoing:** Build out frontend test coverage

---

*This review should be updated as issues are resolved. Mark items as [FIXED] with date and PR reference.*
