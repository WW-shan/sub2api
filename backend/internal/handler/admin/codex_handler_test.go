package admin

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
)

func TestCodexHandlerGetAccountsProxiesResponse(t *testing.T) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/accounts" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"accounts":[{"email":"a@example.com"}]}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	h := NewCodexHandler()
	r := gin.New()
	r.GET("/accounts", h.GetAccounts)

	req := httptest.NewRequest(http.MethodGet, "/accounts", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d", http.StatusOK, w.Code)
	}

	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("expected json body: %v", err)
	}
	if _, ok := body["accounts"]; !ok {
		t.Fatalf("expected accounts field in response")
	}
}

func TestCodexHandlerGetAccountsHandlesInvalidJSON(t *testing.T) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"accounts":`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	h := NewCodexHandler()
	r := gin.New()
	r.GET("/accounts", h.GetAccounts)

	req := httptest.NewRequest(http.MethodGet, "/accounts", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected status %d, got %d", http.StatusBadGateway, w.Code)
	}
}

func TestCodexHandlerResumeProxiesResponse(t *testing.T) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/resume" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"job_phase":"running:pre_resume_check","can_resume":false}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	h := NewCodexHandler()
	r := gin.New()
	r.POST("/resume", h.Resume)

	req := httptest.NewRequest(http.MethodPost, "/resume", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("expected status %d, got %d", http.StatusOK, w.Code)
	}

	var body map[string]any
	if err := json.Unmarshal(w.Body.Bytes(), &body); err != nil {
		t.Fatalf("expected json body: %v", err)
	}
	if got := body["job_phase"]; got != "running:pre_resume_check" {
		t.Fatalf("expected job_phase running:pre_resume_check, got %v", got)
	}
}

func TestCodexHandlerResumeHandlesInvalidJSON(t *testing.T) {
	t.Helper()
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"job_phase":`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	h := NewCodexHandler()
	r := gin.New()
	r.POST("/resume", h.Resume)

	req := httptest.NewRequest(http.MethodPost, "/resume", nil)
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)

	if w.Code != http.StatusBadGateway {
		t.Fatalf("expected status %d, got %d", http.StatusBadGateway, w.Code)
	}
}
