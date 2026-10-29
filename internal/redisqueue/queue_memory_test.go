package redisqueue

import (
	"fmt"
	"testing"
	"time"
)

func TestPopOldestReleasesConsumedPayloads(t *testing.T) {
	for _, count := range []int{1, 3, 5} {
		t.Run(fmt.Sprintf("pop_%d", count), func(t *testing.T) {
			backing := make([]queueItem, 5)
			now := time.Now()
			for i := range backing {
				backing[i] = queueItem{enqueuedAt: now, payload: []byte(fmt.Sprintf("record-%d", i))}
			}
			q := &queue{items: backing}
			out := q.popOldest(count)
			if len(out) != count {
				t.Fatalf("popped %d records, want %d", len(out), count)
			}
			for i, payload := range out {
				if string(payload) != fmt.Sprintf("record-%d", i) {
					t.Fatalf("popped record %d changed: %q", i, payload)
				}
				if backing[i].payload != nil {
					t.Fatalf("consumed slot %d still retains its payload", i)
				}
			}
			if remaining := len(q.items) - q.head; remaining != len(backing)-count {
				t.Fatalf("remaining records = %d, want %d", remaining, len(backing)-count)
			}
			if count < len(backing) {
				for i, payload := range q.popOldest(len(backing)) {
					if string(payload) != fmt.Sprintf("record-%d", count+i) {
						t.Fatalf("remaining record %d changed: %q", i, payload)
					}
				}
			}
			if q.items != nil || q.head != 0 {
				t.Fatal("drained queue still retains its backing allocation")
			}
		})
	}
}

func TestPruneReleasesExpiredPayloads(t *testing.T) {
	for _, count := range []int{1, 3, 5} {
		t.Run(fmt.Sprintf("expired_%d", count), func(t *testing.T) {
			now := time.Date(2026, time.October, 30, 0, 0, 0, 0, time.UTC)
			backing := make([]queueItem, 5)
			for i := range backing {
				enqueuedAt := now
				if i < count {
					enqueuedAt = now.Add(-time.Duration(maxRetentionSeconds+1) * time.Second)
				}
				backing[i] = queueItem{enqueuedAt: enqueuedAt, payload: []byte(fmt.Sprintf("record-%d", i))}
			}
			q := &queue{items: backing}
			q.pruneLocked(now)
			if remaining := len(q.items) - q.head; remaining != len(backing)-count {
				t.Fatalf("remaining records = %d, want %d", remaining, len(backing)-count)
			}
			for i := range backing {
				if i < count {
					if backing[i].payload != nil {
						t.Fatalf("expired slot %d still retains its payload", i)
					}
				} else if string(backing[i].payload) != fmt.Sprintf("record-%d", i) {
					t.Fatalf("live record %d changed: %q", i, backing[i].payload)
				}
			}
		})
	}
}
