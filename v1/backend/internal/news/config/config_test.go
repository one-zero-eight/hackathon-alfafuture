package config

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

const testDatabaseURL = "postgres://news:dummy-password@localhost:5432/news?sslmode=disable"

func isolate(t *testing.T) {
	t.Helper()
	t.Chdir(t.TempDir())
	for _, name := range []string{
		"ENV_FILE", "DATABASE_URL", "HTTP_ADDR", "POLL_INTERVAL", "FETCH_TIMEOUT", "LLM_TIMEOUT",
		"FETCH_MAX_MB", "RBC_FEED_URL", "KOMMERSANT_FEED_URL", "CBR_FEED_URL",
	} {
		t.Setenv(name, "")
		if err := os.Unsetenv(name); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("DATABASE_URL", testDatabaseURL)
}

func writeEnv(t *testing.T, path, contents string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(contents), 0600); err != nil {
		t.Fatal(err)
	}
}

func TestLoadDefaultsWithoutDotenv(t *testing.T) {
	isolate(t)
	got, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	want := Config{
		DatabaseURL:       testDatabaseURL,
		HTTPAddr:          "127.0.0.1:8080",
		PollInterval:      10 * time.Minute,
		FetchTimeout:      30 * time.Second,
		LLMTimeout:        2 * time.Minute,
		FetchMaxBytes:     8_000_000,
		RBCFeedURL:        "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
		KommersantFeedURL: "https://www.kommersant.ru/RSS/news.xml",
		CBRFeedURL:        "https://www.cbr.ru/rss/eventrss",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unexpected defaults: %+v", got)
	}
}

func TestLoadDefaultDotenv(t *testing.T) {
	isolate(t)
	if err := os.Unsetenv("DATABASE_URL"); err != nil {
		t.Fatal(err)
	}
	writeEnv(t, ".env", "# local settings\nDATABASE_URL='"+testDatabaseURL+"'\nexport HTTP_ADDR=:9000\n")
	got, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	if got.DatabaseURL != testDatabaseURL || got.HTTPAddr != ":9000" || os.Getenv("HTTP_ADDR") != ":9000" {
		t.Fatal("default .env was not loaded into configuration and process environment")
	}
}

func TestLoadExplicitFileAndEnvironmentPrecedence(t *testing.T) {
	isolate(t)
	writeEnv(t, ".env", "invalid=\"unterminated")
	path := filepath.Join(t.TempDir(), "custom.env")
	writeEnv(t, path, `DATABASE_URL=postgresql://file-user:file-password@localhost/file-db
HTTP_ADDR=[::1]:9001
POLL_INTERVAL=5m
FETCH_TIMEOUT=12s
LLM_TIMEOUT=45s
FETCH_MAX_MB=2
RBC_FEED_URL=https://rssexport.rbc.ru:443/custom.rss
KOMMERSANT_FEED_URL=https://www.kommersant.ru/custom.xml
CBR_FEED_URL=https://www.cbr.ru/custom.rss
`)
	t.Setenv("ENV_FILE", path)
	t.Setenv("POLL_INTERVAL", "2m")
	got, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	want := Config{
		DatabaseURL:       testDatabaseURL,
		HTTPAddr:          "[::1]:9001",
		PollInterval:      2 * time.Minute,
		FetchTimeout:      12 * time.Second,
		LLMTimeout:        45 * time.Second,
		FetchMaxBytes:     2_000_000,
		RBCFeedURL:        "https://rssexport.rbc.ru:443/custom.rss",
		KommersantFeedURL: "https://www.kommersant.ru/custom.xml",
		CBRFeedURL:        "https://www.cbr.ru/custom.rss",
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("unexpected config: %+v", got)
	}
}

func TestLoadEmptyEnvironmentWinsOverFile(t *testing.T) {
	for _, name := range []string{"DATABASE_URL", "HTTP_ADDR", "POLL_INTERVAL"} {
		t.Run(name, func(t *testing.T) {
			isolate(t)
			writeEnv(t, ".env", "DATABASE_URL="+testDatabaseURL+"\nHTTP_ADDR=:9000\nPOLL_INTERVAL=3m\n")
			t.Setenv(name, "")
			if _, err := Load(); err == nil || !strings.Contains(err.Error(), name) {
				t.Fatalf("empty %s should override the file and fail validation: %v", name, err)
			}
		})
	}
}

func TestLoadInvalidSettings(t *testing.T) {
	for _, tc := range []struct{ name, value string }{
		{"DATABASE_URL", ""},
		{"DATABASE_URL", "mysql://user:do-not-log@localhost/db"},
		{"DATABASE_URL", "postgres://user:do-not-log@host:invalid/db"},
		{"DATABASE_URL", "postgres://localhost:65536/db"},
		{"DATABASE_URL", "postgres:///db"},
		{"DATABASE_URL", "postgres://localhost/db#fragment"},
		{"HTTP_ADDR", ""},
		{"HTTP_ADDR", "localhost"},
		{"HTTP_ADDR", "localhost:0"},
		{"HTTP_ADDR", "localhost:65536"},
		{"HTTP_ADDR", "localhost:+8080"},
		{"HTTP_ADDR", "::1:8080"},
		{"POLL_INTERVAL", "0s"},
		{"POLL_INTERVAL", "-1m"},
		{"POLL_INTERVAL", "do-not-log"},
		{"FETCH_TIMEOUT", "0s"},
		{"FETCH_TIMEOUT", "999999999999999999999s"},
		{"LLM_TIMEOUT", ""},
		{"LLM_TIMEOUT", "0s"},
		{"LLM_TIMEOUT", "-1s"},
		{"LLM_TIMEOUT", "do-not-log"},
		{"FETCH_MAX_MB", ""},
		{"FETCH_MAX_MB", "0"},
		{"FETCH_MAX_MB", "-1"},
		{"FETCH_MAX_MB", "1.5"},
		{"FETCH_MAX_MB", "1MiB"},
		{"FETCH_MAX_MB", "9223372036855"},
		{"FETCH_MAX_MB", "9223372036854775808"},
		{"RBC_FEED_URL", ""},
		{"RBC_FEED_URL", "http://rssexport.rbc.ru/feed"},
		{"RBC_FEED_URL", "https://rssexport.rbc.ru.attacker.example/feed"},
		{"RBC_FEED_URL", "https://user:do-not-log@rssexport.rbc.ru/feed"},
		{"RBC_FEED_URL", "https://rssexport.rbc.ru:8443/feed"},
		{"RBC_FEED_URL", "https://rssexport.rbc.ru/feed#fragment"},
		{"KOMMERSANT_FEED_URL", "https://www.cbr.ru/feed"},
		{"CBR_FEED_URL", "https://127.0.0.1/feed"},
	} {
		t.Run(tc.name+"/"+tc.value, func(t *testing.T) {
			isolate(t)
			t.Setenv(tc.name, tc.value)
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), tc.name) {
				t.Fatalf("expected validation error for %s: %v", tc.name, err)
			}
			if strings.Contains(err.Error(), "do-not-log") {
				t.Fatalf("configuration error exposed a setting value: %v", err)
			}
		})
	}
}

func TestLoadFetchMegabytesConvertedToBytes(t *testing.T) {
	for _, tc := range []struct {
		megabytes string
		bytes     int64
	}{
		{"1", 1_000_000},
		{"9223372036854", 9_223_372_036_854_000_000},
	} {
		t.Run(tc.megabytes, func(t *testing.T) {
			isolate(t)
			t.Setenv("FETCH_MAX_MB", tc.megabytes)
			got, err := Load()
			if err != nil {
				t.Fatal(err)
			}
			if got.FetchMaxBytes != tc.bytes {
				t.Fatalf("got %d bytes, want %d", got.FetchMaxBytes, tc.bytes)
			}
		})
	}
}

func TestLoadDotenvErrorsDoNotExposeContentsOrPath(t *testing.T) {
	for _, kind := range []string{"missing", "malformed", "directory"} {
		t.Run(kind, func(t *testing.T) {
			isolate(t)
			path := filepath.Join(t.TempDir(), "do-not-log.env")
			if kind == "malformed" {
				writeEnv(t, path, "DATABASE_URL=\"postgres://user:do-not-log@localhost/db")
			}
			if kind == "directory" {
				if err := os.Mkdir(path, 0700); err != nil {
					t.Fatal(err)
				}
			}
			t.Setenv("ENV_FILE", path)
			_, err := Load()
			if err == nil || !strings.Contains(err.Error(), "ENV_FILE") || strings.Contains(err.Error(), "do-not-log") {
				t.Fatalf("expected safe file loading error: %v", err)
			}
		})
	}
	for _, value := range []string{"", "BAD=\"unterminated do-not-log"} {
		t.Run("default-file/"+value, func(t *testing.T) {
			isolate(t)
			t.Setenv("ENV_FILE", "")
			if value != "" {
				writeEnv(t, ".env", value)
			}
			_, err := Load()
			if value == "" && err != nil {
				t.Fatal("empty ENV_FILE should select an optional .env:", err)
			}
			if value != "" && (err == nil || strings.Contains(err.Error(), "do-not-log")) {
				t.Fatalf("malformed default .env should fail safely: %v", err)
			}
		})
	}
}

func TestEnvExampleIsValid(t *testing.T) {
	contents, err := os.ReadFile("../../../.env.example")
	if err != nil {
		t.Fatal(err)
	}
	isolate(t)
	if err := os.Unsetenv("DATABASE_URL"); err != nil {
		t.Fatal(err)
	}
	writeEnv(t, ".env", string(contents))
	if _, err := Load(); err != nil {
		t.Fatalf(".env.example is invalid: %v", err)
	}
}
