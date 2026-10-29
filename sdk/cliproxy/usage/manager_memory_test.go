package usage

import (
	"context"
	"reflect"
	"testing"
	"time"
)

type gatedUsageMemoryPlugin struct {
	delivered chan queueItem
	resume    <-chan struct{}
}

func (p *gatedUsageMemoryPlugin) HandleUsage(ctx context.Context, record Record) {
	p.delivered <- queueItem{ctx: ctx, record: record}
	<-p.resume
}

func TestManagerReleasesDequeuedReferences(t *testing.T) {
	type contextKey struct{}
	want := []queueItem{
		{ctx: context.WithValue(context.Background(), contextKey{}, []byte("first context")), record: Record{RequestID: "first", Generate: GenerateFlag(true)}},
		{ctx: context.WithValue(context.Background(), contextKey{}, []byte("second context")), record: Record{RequestID: "second", Generate: GenerateFlag(false)}},
		{ctx: context.WithValue(context.Background(), contextKey{}, []byte("third context")), record: Record{RequestID: "third", Generate: GenerateFlag(true)}},
	}
	// Keep an alias to the original allocation so reference release is checked
	// independently of garbage collection and slice compaction.
	backing := make([]queueItem, len(want), 8)
	copy(backing, want)
	mgr := NewManager(0)
	mgr.queue = backing
	resume := make(chan struct{})
	plugin := &gatedUsageMemoryPlugin{delivered: make(chan queueItem, len(want)), resume: resume}
	mgr.Register(plugin)
	done := make(chan struct{})
	go func() {
		mgr.run(context.Background())
		close(done)
	}()
	t.Cleanup(func() {
		mgr.Stop()
		close(resume)
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("usage dispatcher did not stop")
		}
	})

	for i, expected := range want {
		select {
		case got := <-plugin.delivered:
			if got.ctx != expected.ctx || !reflect.DeepEqual(got.record, expected.record) {
				t.Fatalf("delivery %d did not preserve its context and record", i)
			}
		case <-time.After(5 * time.Second):
			t.Fatalf("timed out waiting for delivery %d", i)
		}
		func() {
			mgr.mu.Lock()
			defer mgr.mu.Unlock()
			for released := 0; released <= i; released++ {
				if !reflect.ValueOf(backing[released]).IsZero() {
					t.Fatalf("consumed queue slot %d still retains its context or record", released)
				}
			}
			if remaining := len(want) - i - 1; len(mgr.queue) != remaining {
				t.Fatalf("queued records = %d, want %d", len(mgr.queue), remaining)
			}
			if i == len(want)-1 && mgr.queue != nil {
				t.Fatal("drained queue still retains its backing allocation")
			}
		}()
		resume <- struct{}{}
	}
}
