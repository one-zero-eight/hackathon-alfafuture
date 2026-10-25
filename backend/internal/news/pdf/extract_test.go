package pdf

import (
	"bytes"
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func sourceFile(t *testing.T) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "-source with spaces.pdf")
	if err := os.WriteFile(path, []byte("%PDF-1.4\n"), 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestPageCountValidatesMetadataAndSource(t *testing.T) {
	path := sourceFile(t)
	for _, output := range []string{"Pages: 3\n", "Title: arbitrary\nPages:          3\n"} {
		e := Extractor{run: func(_ context.Context, tool string, args ...string) ([]byte, error) {
			if tool != "pdfinfo" || !reflect.DeepEqual(args, []string{path}) {
				t.Fatal("unexpected metadata command")
			}
			return []byte(output), nil
		}}
		if got, err := e.PageCount(t.Context(), path); err != nil || got != 3 {
			t.Fatalf("wrong page count: %d %v", got, err)
		}
	}
	for _, output := range []string{"", "Pages: 0", "Pages: -1", "Pages: x", "Pages: 1\nPages: 2", "Pages: 999999999999999999999999", "Pages: 1\x00", "Pages: 1\xff"} {
		e := Extractor{run: func(context.Context, string, ...string) ([]byte, error) { return []byte(output), nil }}
		if _, err := e.PageCount(t.Context(), path); err == nil {
			t.Fatalf("invalid metadata accepted: %q", output)
		}
	}
	e := Extractor{run: func(context.Context, string, ...string) ([]byte, error) {
		t.Fatal("invalid source reached an external command")
		return nil, nil
	}}
	for _, path := range []string{"", t.TempDir(), filepath.Join(t.TempDir(), "absent.pdf")} {
		if _, err := e.PageCount(t.Context(), path); err == nil || strings.Contains(err.Error(), path) && path != "" {
			t.Fatal("invalid source accepted or path exposed")
		}
	}
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if _, err := e.PageCount(ctx, path); !errors.Is(err, context.Canceled) {
		t.Fatal("cancellation ignored", err)
	}
	if _, err := e.ExtractPage(t.Context(), path, 0); err == nil {
		t.Fatal("nonpositive page accepted")
	}
}

func TestExtractPageUsesEmbeddedTextBeforeOCR(t *testing.T) {
	path := sourceFile(t)
	e := Extractor{run: func(_ context.Context, tool string, args ...string) ([]byte, error) {
		want := []string{"-f", "2", "-l", "2", "-layout", "-enc", "UTF-8", "-nopgbrk", path, "-"}
		if tool != "pdftotext" || !reflect.DeepEqual(args, want) {
			t.Fatal("embedded text started another command or lost page scope")
		}
		return []byte("\nИсходный  текст\nвторая строка\n\f"), nil
	}}
	page, err := e.ExtractPage(t.Context(), path, 2)
	wantText := "Исходный  текст\nвторая строка"
	if err != nil || page.Number != 2 || page.Method != "embedded_text" || page.Text != wantText || page.TextSHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(wantText))) {
		t.Fatalf("page text, method or provenance changed: %+v %v", page, err)
	}
}

func TestExtractPageOCRSequenceErrorsAndCleanup(t *testing.T) {
	path := sourceFile(t)
	for _, failure := range []string{"", "pdftotext", "pdftoppm", "tesseract", "empty", "invalid_text"} {
		t.Run(failure, func(t *testing.T) {
			var tools []string
			var image string
			e := Extractor{run: func(_ context.Context, tool string, args ...string) ([]byte, error) {
				tools = append(tools, tool)
				if tool == failure {
					return nil, errors.New("private diagnostic and path")
				}
				switch tool {
				case "pdftotext":
					return []byte(" \n\f"), nil
				case "pdftoppm":
					prefix := args[len(args)-1]
					want := []string{"-f", "3", "-l", "3", "-r", "300", "-gray", "-singlefile", "-png", path, prefix}
					if !reflect.DeepEqual(args, want) {
						t.Fatal("wrong page rasterization")
					}
					image = prefix + ".png"
					if err := os.WriteFile(image, []byte("synthetic raster"), 0600); err != nil {
						t.Fatal(err)
					}
					return nil, nil
				case "tesseract":
					if !reflect.DeepEqual(args, []string{image, "stdout", "-l", "rus+eng"}) {
						t.Fatal("OCR language or source changed")
					}
					if failure == "empty" {
						return []byte(" \n"), nil
					}
					if failure == "invalid_text" {
						return []byte{0xff}, nil
					}
					return []byte("\nРаспознанный текст\n"), nil
				}
				t.Fatal("unexpected tool")
				return nil, nil
			}}
			page, err := e.ExtractPage(t.Context(), path, 3)
			if failure == "" {
				if err != nil || page.Method != "ocr" || page.Text != "Распознанный текст" || page.Number != 3 || page.TextSHA256 != fmt.Sprintf("%x", sha256.Sum256([]byte(page.Text))) {
					t.Fatal("wrong OCR page", err)
				}
			} else if err == nil || strings.Contains(err.Error(), "private") || strings.Contains(err.Error(), path) {
				t.Fatal("failure accepted or raw diagnostic exposed", err)
			}
			if failure == "empty" && !errors.Is(err, ErrNoText) {
				t.Fatal("blank OCR page is not distinguishable from tool failure")
			}
			if failure == "" && !reflect.DeepEqual(tools, []string{"pdftotext", "pdftoppm", "tesseract"}) || failure == "pdftotext" && len(tools) != 1 {
				t.Fatal("tool order or stop-on-error changed")
			}
			if image != "" {
				if _, err := os.Stat(filepath.Dir(image)); !errors.Is(err, os.ErrNotExist) {
					t.Fatal("temporary page image was not cleaned")
				}
			}
		})
	}
}

func TestCommandBoundsOutputAndCancels(t *testing.T) {
	t.Setenv("PDF_COMMAND_HELPER", "1")
	output, err := runCommand(t.Context(), os.Args[0], "-test.run=^TestCommandHelper$", "--", "oversized")
	if err == nil || len(output) > maxOutputBytes {
		t.Fatal("command output limit was bypassed")
	}
	ready := filepath.Join(t.TempDir(), "ready")
	t.Setenv("PDF_HELPER_READY", ready)
	ctx, cancel := context.WithTimeout(t.Context(), time.Second)
	defer cancel()
	e := Extractor{run: func(ctx context.Context, _ string, _ ...string) ([]byte, error) {
		return runCommand(ctx, os.Args[0], "-test.run=^TestCommandHelper$", "--", "wait")
	}}
	if _, err := e.ExtractPage(ctx, sourceFile(t), 1); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("command cancellation was not preserved", err)
	}
	if _, err := os.Stat(ready); err != nil {
		t.Fatal("cancellation test did not start the child process")
	}
	t.Setenv("LC_ALL", "fixture-locale")
	t.Setenv("OMP_THREAD_LIMIT", "8")
	output, err = runCommand(t.Context(), os.Args[0], "-test.run=^TestCommandHelper$", "--", "environment")
	if err != nil || string(output) != "C:1" {
		t.Fatal("command locale or OCR thread bound was not enforced", err)
	}
}

func TestCommandHelper(t *testing.T) {
	if os.Getenv("PDF_COMMAND_HELPER") != "1" {
		return
	}
	switch os.Args[len(os.Args)-1] {
	case "environment":
		fmt.Print(os.Getenv("LC_ALL") + ":" + os.Getenv("OMP_THREAD_LIMIT"))
	case "wait":
		if err := os.WriteFile(os.Getenv("PDF_HELPER_READY"), nil, 0600); err != nil {
			os.Exit(2)
		}
		time.Sleep(time.Minute)
	default:
		_, _ = os.Stdout.Write(bytes.Repeat([]byte("x"), maxOutputBytes+1))
	}
	os.Exit(0)
}

func TestRealPDFExtraction(t *testing.T) {
	path := os.Getenv("PDF_TEST_FILE")
	if path == "" {
		t.Skip("set PDF_TEST_FILE to verify installed Poppler/Tesseract on one page")
	}
	var data bytes.Buffer
	data.WriteString("%PDF-1.4\n")
	stream := "BT /F1 18 Tf 72 720 Td (PDF_TEXT_CHECKPOINT) Tj ET"
	objects := []string{
		"<< /Type /Catalog /Pages 2 0 R >>",
		"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
		"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
		"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
		fmt.Sprintf("<< /Length %d >>\nstream\n%s\nendstream", len(stream), stream),
	}
	offsets := []int{0}
	for i, object := range objects {
		offsets = append(offsets, data.Len())
		fmt.Fprintf(&data, "%d 0 obj\n%s\nendobj\n", i+1, object)
	}
	xref := data.Len()
	fmt.Fprintf(&data, "xref\n0 %d\n0000000000 65535 f \n", len(offsets))
	for _, offset := range offsets[1:] {
		fmt.Fprintf(&data, "%010d 00000 n \n", offset)
	}
	fmt.Fprintf(&data, "trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n", len(offsets), xref)
	textPDF := filepath.Join(t.TempDir(), "text.pdf")
	if err := os.WriteFile(textPDF, data.Bytes(), 0600); err != nil {
		t.Fatal(err)
	}
	e := Extractor{}
	if count, err := e.PageCount(t.Context(), textPDF); err != nil || count != 1 {
		t.Fatal("real text-PDF metadata failed", err)
	}
	if page, err := e.ExtractPage(t.Context(), textPDF, 1); err != nil || page.Method != "embedded_text" || page.Text != "PDF_TEXT_CHECKPOINT" {
		t.Fatal("real embedded text extraction failed", err)
	}
	count, err := e.PageCount(t.Context(), path)
	if err != nil {
		t.Fatal(err)
	}
	page, err := e.ExtractPage(t.Context(), path, 1)
	if err != nil || page.Text == "" {
		t.Fatal("real source page extraction failed", err)
	}
	t.Logf("pages=%d page=%d method=%s text_bytes=%d text_sha256=%s", count, page.Number, page.Method, len(page.Text), page.TextSHA256)
}
