package handlers

import (
	"bytes"
	"fmt"
	"math/rand"
	"testing"

	"github.com/klauspost/compress/zstd"
)

// syntheticRequestBody mixes repeated JSON structure and unique text without using request data.
func syntheticRequestBody(size int) []byte {
	pattern := []byte("synthetic message content with a unique identifier and context ")
	body := bytes.Repeat(pattern, (size+len(pattern)-1)/len(pattern))
	body = body[:size]
	rng := rand.New(rand.NewSource(1))
	const alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
	for i := 0; i < len(body); i += 3 {
		body[i] = alphabet[rng.Intn(len(alphabet))]
	}
	return append(append([]byte(`{"messages":[{"role":"user","content":"`), body...), []byte(`"}]}`)...)
}

func BenchmarkDecodeZstdRequestBody(b *testing.B) {
	for _, size := range []int{16 << 10, 1 << 20, 8 << 20} {
		payload := syntheticRequestBody(size)
		for _, frame := range []string{"known-size", "streaming"} {
			var packed bytes.Buffer
			encoder, err := zstd.NewWriter(&packed, zstd.WithEncoderConcurrency(1))
			if err != nil {
				b.Fatal(err)
			}
			var raw []byte
			if frame == "known-size" {
				raw = encoder.EncodeAll(payload, nil)
			} else {
				if _, err = encoder.Write(payload); err != nil {
					b.Fatal(err)
				}
				if err = encoder.Flush(); err != nil {
					b.Fatal(err)
				}
			}
			if err = encoder.Close(); err != nil {
				b.Fatal(err)
			}
			if frame == "streaming" {
				raw = packed.Bytes()
			}
			var header zstd.Header
			if err = header.Decode(raw); err != nil || header.HasFCS != (frame == "known-size") {
				b.Fatalf("unexpected %s frame header: %v", frame, err)
			}
			for _, bounded := range []bool{false, true} {
				limit := int64(0)
				if bounded {
					limit = int64(len(payload))
				}
				b.Run(fmt.Sprintf("%dKiB/%s/bounded=%t", size>>10, frame, bounded), func(b *testing.B) {
					b.ReportAllocs()
					b.SetBytes(int64(len(payload)))
					for b.Loop() {
						decoded, errDecode := decodeZstdRequestBody(raw, limit)
						if errDecode != nil || len(decoded) != len(payload) {
							b.Fatalf("decode returned %d bytes: %v", len(decoded), errDecode)
						}
					}
				})
			}
		}
	}
}
