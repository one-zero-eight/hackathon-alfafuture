// Package config loads and validates the news service environment at startup.
package config

import (
	"errors"
	"math"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/joho/godotenv"
)

type Config struct {
	DatabaseURL       string
	HTTPAddr          string
	PollInterval      time.Duration
	FetchTimeout      time.Duration
	LLMTimeout        time.Duration
	FetchMaxBytes     int64
	RBCFeedURL        string
	KommersantFeedURL string
	CBRFeedURL        string
	SourcesFile       string
	TopicsFile        string
	FeedsEvery        time.Duration
	DeepEvery         time.Duration
	// LLMEnabled turns on tagging and regional geotags; without it the service only collects.
	LLMEnabled bool
}

// Load reads .env or ENV_FILE without replacing existing environment variables.
// Call it once at startup, before starting goroutines; it populates the process environment.
func Load() (Config, error) {
	path := os.Getenv("ENV_FILE")
	explicit := path != ""
	if !explicit {
		path = ".env"
	}
	if err := godotenv.Load(path); err != nil && (explicit || !errors.Is(err, os.ErrNotExist)) {
		// Parser errors can include file contents and credentials.
		return Config{}, errors.New("ENV_FILE cannot be read or parsed")
	}

	c := Config{
		DatabaseURL:       os.Getenv("DATABASE_URL"),
		HTTPAddr:          env("HTTP_ADDR", "127.0.0.1:8080"),
		RBCFeedURL:        env("RBC_FEED_URL", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"),
		KommersantFeedURL: env("KOMMERSANT_FEED_URL", "https://www.kommersant.ru/RSS/news.xml"),
		CBRFeedURL:        env("CBR_FEED_URL", "https://www.cbr.ru/rss/eventrss"),
		SourcesFile:       env("SOURCES_FILE", "sources.json"),
		TopicsFile:        env("TOPICS_FILE", "topics.txt"),
	}
	database, err := url.Parse(c.DatabaseURL)
	if err != nil || (database.Scheme != "postgres" && database.Scheme != "postgresql") || database.Hostname() == "" || (database.Port() != "" && !validPort(database.Port())) {
		return Config{}, errors.New("DATABASE_URL must be a PostgreSQL URL with a host and valid port")
	}
	if database.Fragment != "" {
		return Config{}, errors.New("DATABASE_URL must not contain a fragment")
	}
	_, port, err := net.SplitHostPort(c.HTTPAddr)
	if err != nil || !validPort(port) {
		return Config{}, errors.New("HTTP_ADDR must be host:port with a port from 1 to 65535")
	}
	if c.PollInterval, err = duration("POLL_INTERVAL", "10m"); err != nil {
		return Config{}, err
	}
	if c.FetchTimeout, err = duration("FETCH_TIMEOUT", "30s"); err != nil {
		return Config{}, err
	}
	if c.LLMTimeout, err = duration("LLM_TIMEOUT", "2m"); err != nil {
		return Config{}, err
	}
	if c.FeedsEvery, err = duration("FEEDS_EVERY", "15m"); err != nil {
		return Config{}, err
	}
	if c.DeepEvery, err = duration("DEEP_EVERY", "6h"); err != nil {
		return Config{}, err
	}
	if c.LLMEnabled, err = strconv.ParseBool(env("LLM_ENABLED", "true")); err != nil {
		return Config{}, errors.New("LLM_ENABLED must be true or false")
	}
	const bytesPerMB = 1_000_000
	maxMB, err := strconv.ParseInt(env("FETCH_MAX_MB", "8"), 10, 64)
	if err != nil || maxMB <= 0 || maxMB > math.MaxInt64/bytesPerMB {
		return Config{}, errors.New("FETCH_MAX_MB must be a positive integer whose byte size fits int64")
	}
	c.FetchMaxBytes = maxMB * bytesPerMB
	for _, source := range []struct{ name, value, host string }{
		{"RBC_FEED_URL", c.RBCFeedURL, "rssexport.rbc.ru"},
		{"KOMMERSANT_FEED_URL", c.KommersantFeedURL, "www.kommersant.ru"},
		{"CBR_FEED_URL", c.CBRFeedURL, "www.cbr.ru"},
	} {
		u, err := url.Parse(source.value)
		if err != nil || u.Scheme != "https" || !strings.EqualFold(u.Hostname(), source.host) || (u.Port() != "" && u.Port() != "443") || u.User != nil || u.Fragment != "" {
			return Config{}, errors.New(source.name + " must use its publisher HTTPS host on port 443, without credentials or a fragment")
		}
	}
	return c, nil
}

func env(name, fallback string) string {
	if value, exists := os.LookupEnv(name); exists {
		return value
	}
	return fallback
}

func validPort(value string) bool {
	n, err := strconv.ParseUint(value, 10, 16)
	return err == nil && n > 0
}

func duration(name, fallback string) (time.Duration, error) {
	value, err := time.ParseDuration(env(name, fallback))
	if err != nil || value <= 0 {
		return 0, errors.New(name + " must be a positive Go duration")
	}
	return value, nil
}
