package main

import (
	"context"
	"errors"
	"reflect"
	"strings"
	"testing"
)

type fakeREST struct {
	responses [][]byte
	errAt     int
	calls     []string
}

type contextREST struct{}

func (contextREST) RestGet(ctx context.Context, _ string) ([]byte, error) {
	<-ctx.Done()
	return nil, ctx.Err()
}

func (f *fakeREST) RestGet(_ context.Context, endpoint string) ([]byte, error) {
	f.calls = append(f.calls, endpoint)
	index := len(f.calls) - 1
	if f.errAt > 0 && len(f.calls) == f.errAt {
		return nil, errors.New("request failed")
	}
	if index >= len(f.responses) {
		return nil, errors.New("unexpected request")
	}
	return f.responses[index], nil
}

func TestGetQuotasTypeFilteringAndPagination(t *testing.T) {
	fake := &fakeREST{responses: [][]byte{
		[]byte(`{"quotas":[{"id":"directory-id","path":"/ifs/data","type":"directory"}],"resume":"next token"}`),
		[]byte(`{"quotas":[{"id":"directory-id-2","path":"/ifs/archive","type":"directory"}],"resume":null}`),
		[]byte(`{"quotas":[{"id":"default-id","path":"/ifs/projects","type":"default-directory"}],"resume":null}`),
	}}

	got, err := getQuotas(context.Background(), fake, defaultQuotaTypes, false, 250, 10)
	if err != nil {
		t.Fatalf("getQuotas returned error: %v", err)
	}
	if len(got) != 3 {
		t.Fatalf("got %d quotas, want 3", len(got))
	}
	wantCalls := []string{
		quotaAPIPath + "?limit=250&type=directory",
		quotaAPIPath + "?resume=next+token",
		quotaAPIPath + "?limit=250&type=default-directory",
	}
	if !reflect.DeepEqual(fake.calls, wantCalls) {
		t.Fatalf("calls = %#v, want %#v", fake.calls, wantCalls)
	}
}

func TestGetQuotasResolveNames(t *testing.T) {
	fake := &fakeREST{responses: [][]byte{[]byte(`{"quotas":[],"resume":null}`)}}
	_, err := getQuotas(context.Background(), fake, []string{quotaTypeUser}, true, 1000, 10)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(fake.calls[0], "resolve_names=true") {
		t.Fatalf("request did not enable name resolution: %s", fake.calls[0])
	}
}

func TestGetQuotasCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err := getQuotas(ctx, contextREST{}, []string{quotaTypeDirectory}, false, 1000, 10)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("error = %v, want context.Canceled", err)
	}
}

func TestGetQuotasRejectsPartialAndInvalidSnapshots(t *testing.T) {
	tests := []struct {
		name    string
		fake    *fakeREST
		max     int
		wantErr string
	}{
		{
			name: "partial page failure",
			fake: &fakeREST{responses: [][]byte{
				[]byte(`{"quotas":[{"id":"one","path":"/ifs/one","type":"directory"}],"resume":"next"}`),
			}, errAt: 2},
			max:     10,
			wantErr: "request failed",
		},
		{
			name: "limit",
			fake: &fakeREST{responses: [][]byte{
				[]byte(`{"quotas":[{"id":"one","path":"/ifs/one","type":"directory"},{"id":"two","path":"/ifs/two","type":"directory"}],"resume":null}`),
			}},
			max:     1,
			wantErr: "max_quotas",
		},
		{
			name: "wrong type",
			fake: &fakeREST{responses: [][]byte{
				[]byte(`{"quotas":[{"id":"one","path":"/ifs/one","type":"user"}],"resume":null}`),
			}},
			max:     10,
			wantErr: "unexpected type",
		},
		{
			name: "missing identity",
			fake: &fakeREST{responses: [][]byte{
				[]byte(`{"quotas":[{"id":"one","type":"directory"}],"resume":null}`),
			}},
			max:     10,
			wantErr: "missing id, path, or type",
		},
		{
			name: "repeated resume token",
			fake: &fakeREST{responses: [][]byte{
				[]byte(`{"quotas":[],"resume":"same"}`),
				[]byte(`{"quotas":[],"resume":"same"}`),
			}},
			max:     10,
			wantErr: "repeated resume token",
		},
		{
			name: "API error envelope",
			fake: &fakeREST{responses: [][]byte{
				[]byte(`{"errors":[{"code":"AEC_FORBIDDEN","message":"not authorized"}]}`),
			}},
			max:     10,
			wantErr: "not authorized",
		},
		{
			name:    "missing quotas",
			fake:    &fakeREST{responses: [][]byte{[]byte(`{"resume":null}`)}},
			max:     10,
			wantErr: "missing quotas",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := getQuotas(context.Background(), test.fake, []string{quotaTypeDirectory}, false, 100, test.max)
			if err == nil || !strings.Contains(err.Error(), test.wantErr) {
				t.Fatalf("error = %v, want substring %q", err, test.wantErr)
			}
		})
	}
}

func TestDecodeVersionEightFixture(t *testing.T) {
	fake := &fakeREST{responses: [][]byte{[]byte(`{
        "quotas": [{
          "container": false,
          "efficiency_ratio": 0.75,
          "enforced": true,
          "id": "12345678901234567890123456789012",
          "include_snapshots": false,
          "linked": null,
          "notifications": "default",
          "path": "/ifs/projects",
          "persona": null,
          "ready": true,
          "thresholds": {"advisory": 80, "advisory_exceeded": false, "advisory_last_exceeded": null, "hard": 100, "hard_exceeded": false, "hard_last_exceeded": null, "percent_advisory": null, "percent_soft": null, "soft": 90, "soft_exceeded": false, "soft_grace": 604800, "soft_last_exceeded": null},
          "thresholds_on": "fslogicalsize",
          "type": "directory",
          "usage": {"applogical": 40, "applogical_ready": true, "fslogical": 50, "fslogical_ready": true, "fsphysical": 70, "fsphysical_ready": true, "inodes": 5, "inodes_ready": true, "physical": 70, "physical_ready": true, "shadow_refs": 0, "shadow_refs_ready": true}
        }],
        "resume": null
      }`)}}
	got, err := getQuotas(context.Background(), fake, []string{quotaTypeDirectory}, false, 100, 10)
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Usage.FSLogical == nil || *got[0].Usage.FSLogical != 50 {
		t.Fatalf("unexpected decoded fixture: %#v", got)
	}
}
