# Proxy Save Button Guard Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the proxy save button reflect the same loading/refresh guards enforced by `saveProxyList()` so users do not click a button that silently returns.

**Architecture:** Keep the existing `saveProxyList()` guard as a defensive check. Add a single computed disabled condition in the Vue component and bind the save button to it, then cover the behavior with a focused component test.

**Tech Stack:** Vue 3, Vitest, Vue Test Utils, existing CodexRegistrationCard tests

---

### Task 1: Add failing test for save button disabled state

**Files:**
- Modify: `frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`

- [ ] **Step 1: Write the failing test** for save button being disabled while the component is still loading or refreshing.
- [ ] **Step 2: Run test to verify it fails**
  - Run: `pnpm vitest frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts -t "save button"`
- [ ] **Step 3: Implement minimal component change** in `CodexRegistrationCard.vue`.
- [ ] **Step 4: Run test to verify it passes**
  - Run: `pnpm vitest frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts -t "save button"`

### Task 2: Run focused frontend verification

**Files:**
- Modify: none

- [ ] **Step 1: Run the relevant CodexRegistrationCard tests**
  - Run: `pnpm vitest frontend/src/views/admin/settings/components/__tests__/CodexRegistrationCard.spec.ts`
- [ ] **Step 2: Confirm no regressions in proxy save interactions**
