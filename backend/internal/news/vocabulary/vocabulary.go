// Package vocabulary loads the fixed, versioned news tag vocabulary.
package vocabulary

import (
	_ "embed"
	"encoding/json"
)

//go:embed data/v1.json
var seed []byte

type Vocabulary struct {
	Version                string                     `json:"version"`
	Status                 string                     `json:"status"`
	CreatedAt              string                     `json:"created_at"`
	UpdatedAt              string                     `json:"updated_at"`
	Sources                map[string]json.RawMessage `json:"sources"`
	Selection              map[string]string          `json:"selection"`
	AssignmentRules        map[string][]string        `json:"assignment_rules"`
	Tags                   []Tag                      `json:"tags"`
	ProfileCountryMappings []CountryMapping           `json:"profile_country_mappings"`
	EventStatuses          []EventStatus              `json:"event_statuses"`
	ResultContract         ResultContract             `json:"result_contract"`
}

type Tag struct {
	ID                   string   `json:"id"`
	Dimension            string   `json:"dimension"`
	Label                string   `json:"label"`
	Definition           string   `json:"definition"`
	InclusionCriteria    string   `json:"inclusion_criteria"`
	ParentID             *string  `json:"parent_id"`
	OKVEDPrefix          string   `json:"okved_prefix,omitempty"`
	Kind                 string   `json:"kind,omitempty"`
	Aliases              []string `json:"aliases,omitempty"`
	ProfileRegionValues  []string `json:"profile_region_values,omitempty"`
	ProfileCountryValues []string `json:"profile_country_values,omitempty"`
	ISOAlpha2            string   `json:"iso_alpha2,omitempty"`
	ISOAlpha3            string   `json:"iso_alpha3,omitempty"`
	ISONumeric           string   `json:"iso_numeric,omitempty"`
	M49Code              string   `json:"m49_code,omitempty"`
	ParentSource         string   `json:"parent_source,omitempty"`
	ReferenceNameEN      string   `json:"reference_name_en,omitempty"`
	ReferenceURL         string   `json:"reference_url,omitempty"`
}

type CountryMapping struct {
	SourceValue string `json:"source_value"`
	TagID       string `json:"tag_id"`
	Mapping     string `json:"mapping"`
}

type EventStatus struct {
	Value      string `json:"value"`
	Label      string `json:"label"`
	Definition string `json:"definition"`
}

type ResultContract struct {
	Description     string          `json:"description"`
	JSONSchema      json.RawMessage `json:"json_schema"`
	ValidationRules []string        `json:"validation_rules"`
}

// Load returns a fresh copy of v1, including its rules, mappings and result schema.
func Load() (Vocabulary, error) {
	var result Vocabulary
	err := json.Unmarshal(seed, &result)
	return result, err
}
