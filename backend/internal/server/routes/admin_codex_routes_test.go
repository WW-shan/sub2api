package routes

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Wei-Shaw/sub2api/internal/handler"
	adminhandler "github.com/Wei-Shaw/sub2api/internal/handler/admin"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
)

func TestRegisterCodexRoutesIncludesResumeEndpoint(t *testing.T) {
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

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{
			Codex: adminhandler.NewCodexHandler(),
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/resume", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.NotEqual(t, http.StatusNotFound, w.Code)
	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesRejectsDeprecatedRunOnceEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{
			Codex: adminhandler.NewCodexHandler(),
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/run-once", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusNotFound, w.Code)
}

func TestRegisterCodexRoutesIncludesRetryEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/retry" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"success":true,"data":{"job_phase":"running:create_parent"},"error":null}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{
			Codex: adminhandler.NewCodexHandler(),
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/retry", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.NotEqual(t, http.StatusNotFound, w.Code)
	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesLoopStatusEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/loop/status" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"running":true,"interval_seconds":30}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{
			Codex: adminhandler.NewCodexHandler(),
		},
	})

	req := httptest.NewRequest(http.MethodGet, "/admin/codex/loop/status", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.NotEqual(t, http.StatusNotFound, w.Code)
	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesLoopStartEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/loop/start" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"running":true,"started":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{
			Codex: adminhandler.NewCodexHandler(),
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/loop/start", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.NotEqual(t, http.StatusNotFound, w.Code)
	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesLoopStopEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/loop/stop" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"running":false,"stopped":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{
			Codex: adminhandler.NewCodexHandler(),
		},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/loop/stop", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.NotEqual(t, http.StatusNotFound, w.Code)
	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesProxyStatusEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/proxy/status" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"enabled":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{Codex: adminhandler.NewCodexHandler()},
	})

	req := httptest.NewRequest(http.MethodGet, "/admin/codex/proxy/status", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesProxyListEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/proxy/list" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{Codex: adminhandler.NewCodexHandler()},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/proxy/list", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesProxySelectEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/proxy/select" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{Codex: adminhandler.NewCodexHandler()},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/proxy/select", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesIncludesProxyTestEndpoint(t *testing.T) {
	gin.SetMode(gin.TestMode)

	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/proxy/test" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{Codex: adminhandler.NewCodexHandler()},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/proxy/test", nil)
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}

func TestRegisterCodexRoutesForwardsProxyPostBody(t *testing.T) {
	gin.SetMode(gin.TestMode)

	expectedBody := `{"proxy_id":"proxy-1"}`
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}
		if r.URL.Path != "/proxy/select" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		actualBody, err := io.ReadAll(r.Body)
		require.NoError(t, err)
		require.JSONEq(t, expectedBody, string(actualBody))

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"ok":true}`))
	}))
	defer upstream.Close()

	t.Setenv("CODEX_REGISTER_BASE_URL", upstream.URL)

	router := gin.New()
	adminGroup := router.Group("/admin")
	registerCodexRoutes(adminGroup, &handler.Handlers{
		Admin: &handler.AdminHandlers{Codex: adminhandler.NewCodexHandler()},
	})

	req := httptest.NewRequest(http.MethodPost, "/admin/codex/proxy/select", strings.NewReader(expectedBody))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	router.ServeHTTP(w, req)

	require.Equal(t, http.StatusOK, w.Code)
}
