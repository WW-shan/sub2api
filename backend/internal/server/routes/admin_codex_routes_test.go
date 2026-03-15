package routes

import (
	"net/http"
	"net/http/httptest"
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
