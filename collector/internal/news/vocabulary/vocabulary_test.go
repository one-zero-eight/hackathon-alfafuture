package vocabulary

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"testing"
)

func loadForTest(t *testing.T) Vocabulary {
	t.Helper()
	v, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestLoadCoversSeedFieldsAndReturnsIndependentCopies(t *testing.T) {
	v := loadForTest(t)
	if v.Version != "v1" || v.Status != "frozen" {
		t.Fatalf("unexpected version/status: %s/%s", v.Version, v.Status)
	}
	decoder := json.NewDecoder(bytes.NewReader(seed))
	decoder.DisallowUnknownFields()
	var checked Vocabulary
	if err := decoder.Decode(&checked); err != nil {
		t.Fatalf("seed fields are not represented by the Go types: %v", err)
	}
	original := loadForTest(t)
	v.Tags[0].Label = "changed"
	v.AssignmentRules["general"][0] = "changed"
	v.Sources["okved"][0] = '!'
	v.ResultContract.JSONSchema[0] = '!'
	if !reflect.DeepEqual(loadForTest(t), original) {
		t.Fatal("mutating a loaded copy changed the embedded vocabulary")
	}
}

func TestTagCoverageAndHierarchy(t *testing.T) {
	v := loadForTest(t)
	byID := make(map[string]Tag)
	counts := make(map[string]int)
	kinds := make(map[string]int)
	classes, subclasses := 0, 0
	okved := regexp.MustCompile(`^\d{2}(?:\.\d{1,2}){0,2}$`)
	for _, tag := range v.Tags {
		if _, exists := byID[tag.ID]; exists {
			t.Fatalf("duplicate ID %s", tag.ID)
		}
		byID[tag.ID] = tag
		counts[tag.Dimension]++
		if !strings.HasPrefix(tag.ID, tag.Dimension+":") || strings.TrimSpace(tag.Label) == "" || strings.TrimSpace(tag.Definition) == "" || strings.TrimSpace(tag.InclusionCriteria) == "" {
			t.Fatalf("incomplete tag: %s", tag.ID)
		}
		if tag.Dimension == "geography" {
			kinds[tag.Kind]++
		}
		if tag.Dimension == "industry" {
			if !okved.MatchString(tag.OKVEDPrefix) || tag.ID != "industry:okved:"+tag.OKVEDPrefix {
				t.Fatalf("invalid OKVED tag: %s", tag.ID)
			}
			if tag.ParentID == nil {
				classes++
				if len(tag.OKVEDPrefix) != 2 {
					t.Fatalf("non-class root: %s", tag.ID)
				}
			} else {
				subclasses++
			}
		}
	}
	if want := map[string]int{"industry": 112, "geography": 365, "economic_group": 4, "resource": 8, "event": 36}; !reflect.DeepEqual(counts, want) {
		t.Fatalf("dimension counts: got %v, want %v", counts, want)
	}
	if classes != 88 || subclasses != 24 {
		t.Fatalf("OKVED classes/subclasses: %d/%d", classes, subclasses)
	}
	if want := map[string]int{"country_area": 249, "world": 1, "world_region": 5, "subregion": 17, "intermediate_region": 7, "profile_region": 82, "scope": 2, "profile_area": 2}; !reflect.DeepEqual(kinds, want) {
		t.Fatalf("geography kinds: got %v, want %v", kinds, want)
	}
	for _, tag := range v.Tags {
		seen := map[string]bool{tag.ID: true}
		for parentID := tag.ParentID; parentID != nil; {
			parent, exists := byID[*parentID]
			if !exists || seen[*parentID] || parent.Dimension != tag.Dimension {
				t.Fatalf("invalid/cyclic parent for %s: %s", tag.ID, *parentID)
			}
			seen[*parentID] = true
			if tag.Dimension == "industry" && !strings.HasPrefix(strings.ReplaceAll(tag.OKVEDPrefix, ".", ""), strings.ReplaceAll(parent.OKVEDPrefix, ".", "")) {
				t.Fatalf("OKVED parent mismatch: %s -> %s", tag.ID, parent.ID)
			}
			parentID = parent.ParentID
		}
		if (tag.Kind == "profile_region" || tag.Kind == "profile_area" || tag.Dimension == "economic_group") && tag.ParentID != nil {
			t.Fatalf("unapproved inferred parent: %s", tag.ID)
		}
	}
}

func TestGeographyMatchesReferenceSnapshot(t *testing.T) {
	v := loadForTest(t)
	byID := make(map[string]Tag)
	for _, tag := range v.Tags {
		byID[tag.ID] = tag
	}
	var source struct {
		ReferenceFile string `json:"reference_file"`
		SHA256        string `json:"sha256"`
	}
	if err := json.Unmarshal(v.Sources["geography"], &source); err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(filepath.Join("data", source.ReferenceFile))
	if err != nil {
		t.Fatal(err)
	}
	if got := fmt.Sprintf("%x", sha256.Sum256(data)); got != source.SHA256 {
		t.Fatalf("reference hash: got %s, want %s", got, source.SHA256)
	}
	var reference struct {
		ISOCountries []struct {
			Alpha2  string `json:"alpha_2"`
			Alpha3  string `json:"alpha_3"`
			Numeric string `json:"numeric"`
		} `json:"iso_countries"`
		M49EN        [][]string `json:"m49_rows_en"`
		M49RU        [][]string `json:"m49_rows_ru"`
		CuratedLinks []struct {
			CountryAlpha2 string `json:"country_alpha2"`
			ParentM49     string `json:"parent_m49"`
			SourceURL     string `json:"source_url"`
		} `json:"curated_geographic_links"`
	}
	if err := json.Unmarshal(data, &reference); err != nil {
		t.Fatal(err)
	}
	if len(reference.ISOCountries) != 249 || len(reference.M49EN) != 248 || len(reference.M49RU) != 248 {
		t.Fatal("incomplete reference snapshot")
	}
	for _, country := range reference.ISOCountries {
		tag := byID["geography:country:"+country.Alpha2]
		if tag.ISOAlpha2 != country.Alpha2 || tag.ISOAlpha3 != country.Alpha3 || tag.ISONumeric != country.Numeric {
			t.Fatalf("ISO mismatch: %s", country.Alpha2)
		}
	}
	ruByCode := make(map[string][]string)
	for _, row := range reference.M49RU {
		ruByCode[row[10]] = row
	}
	for _, row := range reference.M49EN {
		ru := ruByCode[row[10]]
		parent := ""
		for _, i := range []int{0, 2, 4, 6} {
			if row[i] == "" {
				continue
			}
			group := byID["geography:m49:"+row[i]]
			if group.M49Code != row[i] || group.Label != ru[i+1] || group.ReferenceNameEN != row[i+1] || (parent == "" && group.ParentID != nil) || (parent != "" && (group.ParentID == nil || *group.ParentID != parent)) {
				t.Fatalf("M49 group mismatch: %s", row[i])
			}
			parent = group.ID
		}
		country := byID["geography:country:"+row[10]]
		if country.ParentID == nil || *country.ParentID != parent || country.ParentSource != "un_m49" || country.ISOAlpha3 != row[11] || country.ISONumeric != row[9] {
			t.Fatalf("M49 country mismatch: %s", row[10])
		}
	}
	tw := byID["geography:country:TW"]
	if tw.ParentID == nil || *tw.ParentID != "geography:m49:030" || tw.ParentSource != "project_curated" || len(reference.CuratedLinks) != 1 {
		t.Fatal("TW must keep its explicitly sourced project link")
	}
	link := reference.CuratedLinks[0]
	if link.CountryAlpha2 != "TW" || link.ParentM49 != "030" || link.SourceURL != "https://tfetp.k12ea.gov.tw/en/tfetp/web/introduction" {
		t.Fatal("missing source for the curated TW link")
	}
	if _, exists := byID["geography:country:EU"]; exists {
		t.Fatal("EU is an economic group, not an ISO country")
	}
}

func TestProfileCountryMappings(t *testing.T) {
	v := loadForTest(t)
	byID := make(map[string]Tag)
	for _, tag := range v.Tags {
		byID[tag.ID] = tag
	}
	if len(v.ProfileCountryMappings) != 128 {
		t.Fatalf("country/area mappings: %d", len(v.ProfileCountryMappings))
	}
	seen := make(map[string]bool)
	kinds := make(map[string]int)
	for _, mapping := range v.ProfileCountryMappings {
		tag := byID[mapping.TagID]
		if seen[mapping.SourceValue] || mapping.SourceValue == "" || !slices.Contains(tag.ProfileCountryValues, mapping.SourceValue) {
			t.Fatalf("invalid mapping: %+v", mapping)
		}
		if (mapping.Mapping == "iso_country_area" && tag.Kind != "country_area") || (mapping.Mapping == "profile_area" && tag.Kind != "profile_area") {
			t.Fatalf("mapping kind mismatch: %+v", mapping)
		}
		seen[mapping.SourceValue] = true
		kinds[mapping.Mapping]++
	}
	if want := map[string]int{"iso_country_area": 126, "profile_area": 2}; !reflect.DeepEqual(kinds, want) {
		t.Fatalf("mapping counts: %v", kinds)
	}
}

func TestResultSchemaUsesOnlyVocabularyIDsAndEventStatuses(t *testing.T) {
	v := loadForTest(t)
	type schema struct {
		Properties map[string]schema `json:"properties"`
		Items      *schema           `json:"items"`
		Enum       []any             `json:"enum"`
	}
	var result schema
	if err := json.Unmarshal(v.ResultContract.JSONSchema, &result); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"tags", "events"} {
		item := result.Properties[field].Items
		if item == nil {
			t.Fatalf("missing result schema: %s", field)
		}
		wantIDs := make(map[string]bool)
		for _, tag := range v.Tags {
			if field == "tags" || tag.Dimension == "event" {
				wantIDs[tag.ID] = true
			}
		}
		ids := item.Properties["tag_id"].Enum
		if len(ids) != len(wantIDs) {
			t.Fatalf("schema %s ID count: %d", field, len(ids))
		}
		for _, rawID := range ids {
			id, ok := rawID.(string)
			if !ok || !wantIDs[id] {
				t.Fatalf("unknown/duplicate schema %s ID: %v", field, rawID)
			}
			delete(wantIDs, id)
		}
	}
	statuses := []any{"observed", "announced_planned", "forecast", nil}
	if got := result.Properties["events"].Items.Properties["status"].Enum; !reflect.DeepEqual(got, statuses) {
		t.Fatalf("event statuses: %v", got)
	}
	if len(v.EventStatuses) != 3 {
		t.Fatal("event status definitions must cover the three named states")
	}
	for i, status := range v.EventStatuses {
		if status.Value != statuses[i] || status.Label == "" || status.Definition == "" {
			t.Fatalf("incomplete event status: %+v", status)
		}
	}
}
