package chat

import (
	"context"

	"lazymind/core/modelconfig"
)

// fetchCloudToolConfig returns tool credentials for all chat-enabled cloud
// connections owned by the current user. It intentionally uses auth-service as
// the source of truth, so providers can share the same dynamic-token flow.
func fetchCloudToolConfig(ctx context.Context, userID string) (map[string]any, error) {
	return modelconfig.LoadCloudToolConfig(ctx, userID)
}
