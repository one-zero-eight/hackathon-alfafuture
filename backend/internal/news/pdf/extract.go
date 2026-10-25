// Package pdf extracts page text locally without interpreting tables or charts.
package pdf

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"
)

const maxOutputBytes = 8_000_000

var ErrNoText = errors.New("PDF page has no extractable text")

type Page struct {
	Number     int    `json:"number"`
	Method     string `json:"method"`
	Text       string `json:"text"`
	TextSHA256 string `json:"text_sha256"`
}

// Extractor's zero value uses installed Poppler and Tesseract commands.
type Extractor struct {
	run func(context.Context, string, ...string) ([]byte, error)
}

func (e Extractor) PageCount(ctx context.Context, path string) (int, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	path, err := sourcePath(ctx, path)
	if err != nil {
		return 0, err
	}
	output, err := e.command(ctx, "pdfinfo", path)
	if err != nil {
		return 0, err
	}
	count := 0
	for _, line := range strings.Split(string(output), "\n") {
		key, value, found := strings.Cut(line, ":")
		if found && key == "Pages" {
			if count != 0 {
				return 0, errors.New("pdfinfo returned duplicate page counts")
			}
			count, err = strconv.Atoi(strings.TrimSpace(value))
			if err != nil || count <= 0 {
				return 0, errors.New("pdfinfo returned an invalid page count")
			}
		}
	}
	if count == 0 {
		return 0, errors.New("pdfinfo returned no page count")
	}
	return count, nil
}

// ExtractPage expects a stable source file; the importer owns the immutable original.
func (e Extractor) ExtractPage(ctx context.Context, path string, number int) (Page, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
	defer cancel()
	path, err := sourcePath(ctx, path)
	if err != nil {
		return Page{}, err
	}
	if number <= 0 {
		return Page{}, errors.New("PDF page number must be positive")
	}
	pageNumber := strconv.Itoa(number)
	output, err := e.command(ctx, "pdftotext", "-f", pageNumber, "-l", pageNumber, "-layout", "-enc", "UTF-8", "-nopgbrk", path, "-")
	if err != nil {
		return Page{}, err
	}
	method := "embedded_text"
	if strings.TrimSpace(string(output)) == "" {
		dir, err := os.MkdirTemp("", "news-pdf-page-")
		if err != nil {
			return Page{}, errors.New("cannot create PDF page workspace")
		}
		defer os.RemoveAll(dir)
		prefix := filepath.Join(dir, "page")
		if _, err := e.command(ctx, "pdftoppm", "-f", pageNumber, "-l", pageNumber, "-r", "300", "-gray", "-singlefile", "-png", path, prefix); err != nil {
			return Page{}, err
		}
		output, err = e.command(ctx, "tesseract", prefix+".png", "stdout", "-l", "rus+eng")
		if err != nil {
			return Page{}, err
		}
		method = "ocr"
	}
	text := strings.TrimSpace(string(output))
	if text == "" {
		return Page{}, ErrNoText
	}
	return Page{Number: number, Method: method, Text: text, TextSHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(text)))}, nil
}

func sourcePath(ctx context.Context, path string) (string, error) {
	if err := ctx.Err(); err != nil {
		return "", err
	}
	if path == "" {
		return "", errors.New("PDF path is required")
	}
	path, err := filepath.Abs(path)
	if err != nil {
		return "", errors.New("cannot resolve PDF path")
	}
	info, err := os.Stat(path)
	if err != nil || !info.Mode().IsRegular() {
		return "", errors.New("PDF must be a readable regular file")
	}
	return path, nil
}

func (e Extractor) command(ctx context.Context, tool string, args ...string) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	run := e.run
	if run == nil {
		run = runCommand
	}
	output, err := run(ctx, tool, args...)
	if ctx.Err() != nil {
		return nil, ctx.Err()
	}
	if err != nil {
		return nil, fmt.Errorf("%s failed or is unavailable", tool)
	}
	if len(output) > maxOutputBytes || !utf8.Valid(output) || bytes.ContainsRune(output, 0) {
		return nil, fmt.Errorf("%s returned invalid or oversized text", tool)
	}
	return output, nil
}

type outputBuffer struct{ buffer bytes.Buffer }

func (b *outputBuffer) Write(p []byte) (int, error) {
	if len(p) > maxOutputBytes-b.buffer.Len() {
		return 0, errors.New("PDF command output exceeds limit")
	}
	return b.buffer.Write(p)
}

func runCommand(ctx context.Context, tool string, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, tool, args...)
	cmd.Env = append(os.Environ(), "LC_ALL=C", "OMP_THREAD_LIMIT=1")
	var output outputBuffer
	cmd.Stdout, cmd.Stderr = &output, io.Discard
	cmd.WaitDelay = time.Second
	err := cmd.Run()
	return output.buffer.Bytes(), err
}
