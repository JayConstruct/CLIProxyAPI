package handlers

import (
	"bytes"
	"errors"
	"github.com/klauspost/compress/zstd"
	"net/http"
	"testing"
)

func TestDecodeZstdBoundedPreallocation(t *testing.T) {
	original := bytes.Repeat([]byte("sample context data "), 400000)
	var packed bytes.Buffer
	encoder, err := zstd.NewWriter(&packed)
	if err != nil {
		t.Fatal(err)
	}
	if _, err = encoder.Write(original); err != nil {
		t.Fatal(err)
	}
	if err = encoder.Close(); err != nil {
		t.Fatal(err)
	}
	decoded, err := decodeZstdRequestBody(packed.Bytes(), int64(len(original)))
	if err != nil || !bytes.Equal(original, decoded) {
		t.Fatalf("roundtrip: %v", err)
	}
	_, err = decodeZstdRequestBody(packed.Bytes(), int64(len(original)-1))
	var limit *http.MaxBytesError
	if !errors.As(err, &limit) {
		t.Fatalf("expected size limit, got %v", err)
	}
	if _, err = decodeZstdRequestBody([]byte("invalid frame"), 1024); err == nil {
		t.Fatal("expected corrupt frame error")
	}
}
