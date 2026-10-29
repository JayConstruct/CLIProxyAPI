package handlers

import (
	"bytes"
	"errors"
	"net/http"
	"testing"

	"github.com/klauspost/compress/zstd"
)

func TestDecodeZstdRequestBodyFrameCompatibility(t *testing.T) {
	payload := bytes.Repeat([]byte(`{"content":"synthetic test message"}`), 5000)
	var stream bytes.Buffer
	encoder, err := zstd.NewWriter(&stream, zstd.WithEncoderConcurrency(1))
	if err != nil {
		t.Fatal(err)
	}
	frame := encoder.EncodeAll(payload, nil)
	if _, err = encoder.Write(payload); err != nil {
		t.Fatal(err)
	}
	if err = encoder.Flush(); err != nil {
		t.Fatal(err)
	}
	if err = encoder.Close(); err != nil {
		t.Fatal(err)
	}
	var header zstd.Header
	if err = header.Decode(stream.Bytes()); err != nil || header.HasFCS {
		t.Fatalf("expected streaming frame without content size: %v", err)
	}
	concatenated := append(append([]byte(nil), frame...), stream.Bytes()...)
	corrupt := append([]byte(nil), frame...)
	corrupt[len(corrupt)-1] ^= 0xff
	skippable := []byte{0x50, 0x2a, 0x4d, 0x18, 0x03, 0x00, 0x00, 0x00, 's', 'k', 'p'}
	for _, tc := range []struct {
		name    string
		raw     []byte
		want    []byte
		limit   int64
		wantErr bool
	}{
		{name: "known size", raw: frame, want: payload},
		{name: "streaming", raw: stream.Bytes(), want: payload},
		{name: "exact limit", raw: frame, want: payload, limit: int64(len(payload))},
		{name: "multiple frames", raw: concatenated, want: bytes.Repeat(payload, 2)},
		{name: "skippable frame", raw: append(skippable, frame...), want: payload},
		{name: "checksum mismatch", raw: corrupt, wantErr: true},
		{name: "truncated", raw: frame[:len(frame)-1], wantErr: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			got, errDecode := decodeZstdRequestBody(tc.raw, tc.limit)
			if tc.wantErr {
				if errDecode == nil {
					t.Fatal("expected frame validation error")
				}
				return
			}
			if errDecode != nil || !bytes.Equal(got, tc.want) {
				t.Fatalf("decoded %d bytes, want %d: %v", len(got), len(tc.want), errDecode)
			}
		})
	}
	for _, raw := range [][]byte{frame, stream.Bytes(), concatenated} {
		_, errDecode := decodeZstdRequestBody(raw, int64(len(payload)-1))
		var limitErr *http.MaxBytesError
		if !errors.As(errDecode, &limitErr) || limitErr.Limit != int64(len(payload)-1) {
			t.Fatalf("expected request size limit error, got %v", errDecode)
		}
	}
}
