package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net/url"
	"strconv"

	"github.com/isilon/powerscale_data_insights/internal/api"
)

const quotaAPIPath = "/platform/8/quota/quotas"

const (
	quotaTypeDirectory        = "directory"
	quotaTypeDefaultDirectory = "default-directory"
	quotaTypeUser             = "user"
	quotaTypeDefaultUser      = "default-user"
	quotaTypeGroup            = "group"
	quotaTypeDefaultGroup     = "default-group"
)

var validQuotaTypes = map[string]struct{}{
	quotaTypeDirectory:        {},
	quotaTypeDefaultDirectory: {},
	quotaTypeUser:             {},
	quotaTypeDefaultUser:      {},
	quotaTypeGroup:            {},
	quotaTypeDefaultGroup:     {},
}

var defaultQuotaTypes = []string{quotaTypeDirectory, quotaTypeDefaultDirectory}

type Cluster struct {
	api.Cluster
}

type quotaPersona struct {
	ID   string  `json:"id"`
	Name *string `json:"name"`
	Type *string `json:"type"`
}

type quotaThresholds struct {
	Advisory             *uint64  `json:"advisory"`
	AdvisoryExceeded     *bool    `json:"advisory_exceeded"`
	AdvisoryLastExceeded *int64   `json:"advisory_last_exceeded"`
	Hard                 *uint64  `json:"hard"`
	HardExceeded         *bool    `json:"hard_exceeded"`
	HardLastExceeded     *int64   `json:"hard_last_exceeded"`
	PercentAdvisory      *float64 `json:"percent_advisory"`
	PercentSoft          *float64 `json:"percent_soft"`
	Soft                 *uint64  `json:"soft"`
	SoftExceeded         *bool    `json:"soft_exceeded"`
	SoftGrace            *int64   `json:"soft_grace"`
	SoftLastExceeded     *int64   `json:"soft_last_exceeded"`
}

type quotaUsage struct {
	AppLogical              *uint64 `json:"applogical"`
	AppLogicalReady         *bool   `json:"applogical_ready"`
	FSLogical               *uint64 `json:"fslogical"`
	FSLogicalReady          *bool   `json:"fslogical_ready"`
	FSPhysical              *uint64 `json:"fsphysical"`
	FSPhysicalReady         *bool   `json:"fsphysical_ready"`
	Inodes                  *uint64 `json:"inodes"`
	InodesReady             *bool   `json:"inodes_ready"`
	Physical                *uint64 `json:"physical"`
	PhysicalReady           *bool   `json:"physical_ready"`
	PhysicalData            *uint64 `json:"physical_data"`
	PhysicalDataReady       *bool   `json:"physical_data_ready"`
	PhysicalProtection      *uint64 `json:"physical_protection"`
	PhysicalProtectionReady *bool   `json:"physical_protection_ready"`
	ShadowRefs              *uint64 `json:"shadow_refs"`
	ShadowRefsReady         *bool   `json:"shadow_refs_ready"`
}

type quota struct {
	Container        bool            `json:"container"`
	Description      string          `json:"description"`
	EfficiencyRatio  *float64        `json:"efficiency_ratio"`
	Enforced         bool            `json:"enforced"`
	ID               string          `json:"id"`
	IncludeSnapshots bool            `json:"include_snapshots"`
	Labels           string          `json:"labels"`
	Linked           *bool           `json:"linked"`
	Path             string          `json:"path"`
	Persona          *quotaPersona   `json:"persona"`
	Ready            bool            `json:"ready"`
	ReductionRatio   *float64        `json:"reduction_ratio"`
	Thresholds       quotaThresholds `json:"thresholds"`
	ThresholdsOn     string          `json:"thresholds_on"`
	Type             string          `json:"type"`
	Usage            quotaUsage      `json:"usage"`
}

type quotaResponse struct {
	Quotas *[]quota        `json:"quotas"`
	Resume *string         `json:"resume"`
	Errors []quotaAPIError `json:"errors"`
}

type quotaAPIError struct {
	Code    string `json:"code"`
	Field   string `json:"field"`
	Message string `json:"message"`
}

type restGetter interface {
	RestGet(context.Context, string) ([]byte, error)
}

// GetQuotas retrieves a complete, type-filtered live quota snapshot. Each
// quota type is paginated independently because a resume token cannot be sent
// with any other query argument.
func (c *Cluster) GetQuotas(ctx context.Context, quotaTypes []string, resolveNames bool, pageLimit, maxQuotas int) ([]quota, error) {
	return getQuotas(ctx, c, quotaTypes, resolveNames, pageLimit, maxQuotas)
}

func getQuotas(ctx context.Context, client restGetter, quotaTypes []string, resolveNames bool, pageLimit, maxQuotas int) ([]quota, error) {
	result := make([]quota, 0)
	seen := make(map[string]struct{})

	for _, quotaType := range quotaTypes {
		seenResume := make(map[string]struct{})
		values := url.Values{}
		values.Set("type", quotaType)
		values.Set("limit", strconv.Itoa(pageLimit))
		if resolveNames {
			values.Set("resolve_names", "true")
		}
		endpoint := quotaAPIPath + "?" + values.Encode()

		for {
			body, err := client.RestGet(ctx, endpoint)
			if err != nil {
				return nil, fmt.Errorf("list %s quotas: %w", quotaType, err)
			}

			var page quotaResponse
			if err := json.Unmarshal(body, &page); err != nil {
				return nil, fmt.Errorf("decode %s quota page: %w", quotaType, err)
			}
			if len(page.Errors) > 0 {
				return nil, fmt.Errorf("list %s quotas: API error %s: %s", quotaType, page.Errors[0].Code, page.Errors[0].Message)
			}
			if page.Quotas == nil {
				return nil, fmt.Errorf("decode %s quota page: response is missing quotas", quotaType)
			}
			for _, q := range *page.Quotas {
				if q.ID == "" || q.Path == "" || q.Type == "" {
					return nil, fmt.Errorf("decode %s quota page: quota is missing id, path, or type", quotaType)
				}
				if q.Type != quotaType {
					return nil, fmt.Errorf("list %s quotas: response contained unexpected type %q", quotaType, q.Type)
				}
				if _, ok := seen[q.ID]; ok {
					return nil, fmt.Errorf("list quotas: duplicate quota id %q", q.ID)
				}
				seen[q.ID] = struct{}{}
				result = append(result, q)
				if maxQuotas > 0 && len(result) > maxQuotas {
					return nil, fmt.Errorf("quota count exceeds configured max_quotas (%d)", maxQuotas)
				}
			}

			if page.Resume == nil || *page.Resume == "" {
				break
			}
			if _, ok := seenResume[*page.Resume]; ok {
				return nil, fmt.Errorf("list %s quotas: repeated resume token", quotaType)
			}
			seenResume[*page.Resume] = struct{}{}
			endpoint = quotaAPIPath + "?" + url.Values{"resume": []string{*page.Resume}}.Encode()
		}
	}

	return result, nil
}
