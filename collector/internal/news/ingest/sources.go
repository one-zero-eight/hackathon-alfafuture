package ingest

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
)

// Source is one entry of sources.json: the curated list of outlets.
//   - URL: RSS/Atom feed; empty for outlets read only through Google News (site:Host).
//   - Native: collected by the built-in full-text collector (RBC, Kommersant, CBR); here only for the Google News depth pass.
//   - Region: geography:region:NNN tag of a regional outlet, null for national ones.
//   - RegionSections: feed categories whose articles are regional without a model check.
type Source struct {
	ID             string   `json:"id"`
	Name           string   `json:"name"`
	URL            string   `json:"url"`
	Host           string   `json:"host"`
	Native         bool     `json:"native"`
	Region         *string  `json:"region"`
	RegionSections []string `json:"region_sections"`
}

func (s Source) region() string {
	if s.Region == nil {
		return ""
	}
	return *s.Region
}

// LoadSources reads and validates the list; a broken file stops the service at startup instead of silently dropping outlets.
func LoadSources(path string) ([]Source, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, errors.New("cannot read the sources file")
	}
	var sources []Source
	if err := json.Unmarshal(data, &sources); err != nil {
		return nil, errors.New("cannot parse the sources file")
	}
	seen := map[string]bool{}
	for _, s := range sources {
		switch {
		case s.ID == "" || s.Name == "" || s.Host == "":
			return nil, fmt.Errorf("source %q requires id, name and host", s.ID)
		case seen[s.ID]:
			return nil, fmt.Errorf("duplicate source id %q", s.ID)
		case !s.Native && s.URL == "" && s.region() == "":
			return nil, fmt.Errorf("source %q has no feed URL and no region: nothing would read it", s.ID)
		}
		seen[s.ID] = true
	}
	return sources, nil
}

// LoadTopics reads one Google News topic per line.
func LoadTopics(path string) ([]string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, errors.New("cannot read the topics file")
	}
	var topics []string
	for _, line := range strings.Split(string(data), "\n") {
		if line = strings.TrimSpace(line); line != "" {
			topics = append(topics, line)
		}
	}
	return topics, nil
}

var errUnknownKind = errors.New(`backfill kind must be "gn" or "gnsite"`)
