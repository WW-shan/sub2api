package admin

import (
	"encoding/json"
	"io"
	"net/http"
	"os"
	"time"

	"github.com/Wei-Shaw/sub2api/internal/pkg/response"

	"github.com/gin-gonic/gin"
)

type CodexHandler struct {
}

func NewCodexHandler() *CodexHandler {
	return &CodexHandler{}
}

func (h *CodexHandler) baseURL() string {
	if v := os.Getenv("CODEX_REGISTER_BASE_URL"); v != "" {
		return v
	}
	return "http://codex-register:5000"
}

func (h *CodexHandler) proxyRequest(c *gin.Context, method string, path string, body io.Reader, timeout time.Duration) {
	client := &http.Client{Timeout: timeout}
	req, err := http.NewRequestWithContext(c.Request.Context(), method, h.baseURL()+path, body)
	if err != nil {
		response.Error(c, http.StatusInternalServerError, err.Error())
		return
	}
	if contentType := c.GetHeader("Content-Type"); contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if token := os.Getenv("CODEX_REGISTER_CONTROL_TOKEN"); token != "" {
		req.Header.Set("X-Codex-Token", token)
	}
	resp, err := client.Do(req)
	if err != nil {
		response.Error(c, http.StatusBadGateway, err.Error())
		return
	}
	defer resp.Body.Close()
	var responseBody any
	if err := json.NewDecoder(resp.Body).Decode(&responseBody); err != nil {
		response.Error(c, http.StatusBadGateway, err.Error())
		return
	}
	c.JSON(resp.StatusCode, responseBody)
}

func (h *CodexHandler) proxyGet(c *gin.Context, path string) {
	h.proxyRequest(c, http.MethodGet, path, nil, 5*time.Second)
}

func (h *CodexHandler) proxyPost(c *gin.Context, path string) {
	h.proxyRequest(c, http.MethodPost, path, c.Request.Body, 10*time.Second)
}

func (h *CodexHandler) GetStatus(c *gin.Context) {
	h.proxyGet(c, "/status")
}

func (h *CodexHandler) GetLogs(c *gin.Context) {
	h.proxyGet(c, "/logs")
}

func (h *CodexHandler) GetAccounts(c *gin.Context) {
	h.proxyGet(c, "/accounts")
}

func (h *CodexHandler) Enable(c *gin.Context) {
	h.proxyPost(c, "/enable")
}

func (h *CodexHandler) Disable(c *gin.Context) {
	h.proxyPost(c, "/disable")
}

func (h *CodexHandler) Resume(c *gin.Context) {
	h.proxyPost(c, "/resume")
}

func (h *CodexHandler) Retry(c *gin.Context) {
	h.proxyPost(c, "/retry")
}

func (h *CodexHandler) GetLoopStatus(c *gin.Context) {
	h.proxyGet(c, "/loop/status")
}

func (h *CodexHandler) StartLoop(c *gin.Context) {
	h.proxyPost(c, "/loop/start")
}

func (h *CodexHandler) StopLoop(c *gin.Context) {
	h.proxyPost(c, "/loop/stop")
}

func (h *CodexHandler) GetProxyStatus(c *gin.Context) {
	h.proxyGet(c, "/proxy/status")
}

func (h *CodexHandler) SaveProxyList(c *gin.Context) {
	h.proxyPost(c, "/proxy/list")
}

func (h *CodexHandler) SelectProxy(c *gin.Context) {
	h.proxyPost(c, "/proxy/select")
}

func (h *CodexHandler) TestProxy(c *gin.Context) {
	h.proxyPost(c, "/proxy/test")
}
